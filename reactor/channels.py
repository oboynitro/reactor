import logging

from asgiref.sync import async_to_sync
from channels.generic.websocket import JsonWebsocketConsumer

from . import json
from .component import RootComponent, Component


log = logging.getLogger('reactor')


class ReactorConsumer(JsonWebsocketConsumer):
    channel_name = ''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.subscriptions = set()

    # Group operations

    def subscribe(self, event):
        room_name = event['room_name']
        if room_name not in self.subscriptions:
            log.debug(f':: SUBSCRIBE {self.channel_name} {room_name}')
            async_to_sync(self.channel_layer.group_add)(
                room_name,
                self.channel_name
            )
            self.subscriptions.add(room_name)

    def unsubscribe(self, event):
        room_name = event['room_name']
        if room_name in self.subscriptions:
            log.debug(f':: UNSUBSCRIBE {self.channel_name} {room_name}')
            async_to_sync(self.channel_layer.group_discard)(
                room_name,
                self.channel_name
            )
            self.subscriptions.discard(room_name)

    # Channel events

    def connect(self):
        super().connect()
        self.scope['channel_name'] = self.channel_name
        self.root_component = RootComponent(context=self.scope)
        self.send_json({
            'type': 'components',
            'component_types': {
                name: c.extends for name, c in Component._all.items()
            }
        })
        log.debug(f':: CONNECT {self.channel_name}')

    def disconnect(self, close_code):
        for room in list(self.subscriptions):
            self.unsubscribe({'room_name': room})
        log.debug(f':: DISCONNECT {self.channel_name}')

    # Dispatching

    def receive_json(self, request):
        name = request['command']
        payload = request['payload']
        getattr(self, f'receive_{name}')(**payload)

    def receive_join(self, tag_name, state):
        log.debug(f'>>> JOIN {tag_name} {state}')
        component = self.root_component.get_or_create(tag_name, **state)
        html_diff = component._render_diff()
        self.render({'id': component.id, 'html_diff': html_diff})

    def receive_user_event(self, id, name, args):
        log.debug(f'>>> USER_EVENT {name} {args}')
        html_diff = self.root_component.dispatch_user_event(id, name, args)
        self.render({'id': id, 'html_diff': html_diff})

    def receive_leave(self, id):
        self.root_component.pop(id)

    # Internal event

    def update(self, event):
        log.debug(f'>>> UPDATE {event}')
        for render_event in self.root_component.propagate_update(event):
            self.render(render_event)

    def send_component(self, event):
        log.debug(f'>>> DISPATCH {event}')
        self.receive_user_event(
            event['state']['id'],
            event['name'],
            event['state']
        )

    # Broadcasters

    def render(self, event):
        if event['html_diff']:
            log.debug(f"<<< RENDER {event['id']}")
            self.send_json(dict(event, type='render'))

    def remove(self, event):
        log.debug(f"<<< REMOVE {event['id']}")
        self.receive_leave(event['id'])
        self.send_json(dict(event, type='remove'))

    def redirect(self, event):
        log.debug(f"<<< REDIRECT {event['url']}")
        self.send_json(dict(event, type='redirect'))

    def push_state(self, event):
        log.debug(f"<<< PUSH-STATE {event['url']}")
        self.send_json(dict(event, type='push_state'))

    def replace_state(self, event):
        log.debug(f"<<< REPLACE-STATE {event['url'], event['title']}")
        self.send_json(dict(event, type='replace_state'))

    @classmethod
    def decode_json(cls, text_data):
        return json.loads(text_data)

    @classmethod
    def encode_json(cls, content):
        return json.dumps(content)
