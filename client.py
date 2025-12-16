#!/usr/bin/env python3
"""CLI WebSocket клиент для минимального чата.

Запуск:
  python client.py --host localhost --port 8000 --chat global --name alice

"""
import asyncio
import argparse
import json
import sys

import websockets


async def run(uri, chat_id, name):
    async with websockets.connect(uri) as ws:
        # join
        await ws.send(json.dumps({"type": "join_chat", "payload": {"chat_id": chat_id}}))

        async def send_loop():
            loop = asyncio.get_event_loop()
            while True:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line:
                    break
                text = line.rstrip('\n')
                if not text:
                    continue
                await ws.send(json.dumps({"type": "send_message", "payload": {"text": text, "user": name}}))

        async def recv_loop():
            async for message in ws:
                try:
                    data = json.loads(message)
                    if data.get('type') == 'history':
                        for m in data.get('payload', {}).get('messages', []):
                            print(f"[{m['timestamp']}] {m['user']}: {m['text']}")
                    elif data.get('type') == 'new_message':
                        m = data.get('payload')
                        print(f"[{m['timestamp']}] {m['user']}: {m['text']}")
                except Exception as e:
                    print('Recv error', e)

        await asyncio.gather(send_loop(), recv_loop())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='localhost')
    parser.add_argument('--port', default=8000, type=int)
    parser.add_argument('--chat', default='global')
    parser.add_argument('--name', default='cli')
    args = parser.parse_args()

    uri = f"ws://{args.host}:{args.port}/ws"
    try:
        asyncio.run(run(uri, args.chat, args.name))
    except KeyboardInterrupt:
        print('\nВыход')


if __name__ == '__main__':
    main()
