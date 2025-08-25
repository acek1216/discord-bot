# -*- coding: utf-8 -*-
"""
Discord Bot & LINE Bot Integrated Version (Llama Test)
"""
import os
import sys
import threading
import asyncio
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent
import discord
from openai import AsyncOpenAI
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from mistralai.async_client import MistralAsyncClient
from notion_client import Client
import requests
import io
from PIL import Image
import datetime
import vertexai
from vertexai.generative_models import GenerativeModel

# --- 環境変数の読み込み ---
# Claude関連のキーを一旦不要にする
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
DISCORD_BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
# (あなたのDiscord Botで必要な他のAPIキー)
# ...

# --- Discord Botの既存コード ---
# (あなたの800行のコードの大部分がここに入ります)
# intents = discord.Intents.default() ...
# client = discord.Client(...)
# async def ask_gpt_base(...): ...
# def _sync_call_llama(p_text: str): ...  <-- この関数を使います
# @client.event
# async def on_ready(): ...
# @client.event
# async def on_message(message): ...
# --- Discord Botの既存コードここまで ---


# --- LINE Bot用Webサーバー（Flask）の初期化と処理 ---
app = Flask(__name__)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)

@app.route("/callback", methods=['POST'])
def callback():
    """LINEからのWebhookを受け取るエンドポイント"""
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=False)
    try:
        handler.handle(body.decode('utf-8'), signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

def call_llama_for_line(user_message):
    """LINE Bot専用: 既存のLlama関数を呼び出す"""
    system_prompt = "あなたは17歳の女執事です。ご主人様（ユーザー）に対して、常に敬語を使いつつも、少し生意気でウィットに富んだ返答を心がけてください。"
    full_prompt = f"{system_prompt}\n\nUser: {user_message}"
    try:
        # あなたの既存のLlama呼び出し関数 (_sync_call_llama) を利用
        reply = _sync_call_llama(full_prompt)
        return reply
    except Exception as e:
        print(f"🛑 ERROR: Llama call for LINE failed: {e}")
        return "申し訳ございません、ご主人様。思考回路に接続できませんでした。"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    """LINEのメッセージイベントを処理する関数"""
    with ApiClient(configuration) as api_client:
        reply_text = call_llama_for_line(event.message.text)
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply_text)])
        )

# --- Gunicornがこのファイルを読み込んだ時点で、Discord Botを起動する ---
def run_discord_bot_in
