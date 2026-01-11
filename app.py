from flask import Flask, render_template, request, jsonify, redirect, url_for
import uuid
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta 

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)
load_dotenv()

CHANNEL_ACCESS_TOKEN = os.environ.get("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.environ.get("CHANNEL_SECRET")
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
events = {}
user_id = None

@app.route('/')
def index():
    return render_template('select_page.html')

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return "Invalid signature", 400
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    global user_id
    user_id = event.source.user_id
    user_message = event.message.text.strip().lower() 

    print(f"--- LINEユーザーIDを取得しました ---")
    print(f"USER ID: {user_id}")
    print(f"メッセージ内容: {user_message}")
    print("-----------------------------------")

    base_url = os.getenv("BASE_URL")

    if user_message in ["日調", "にっちょう", "日程調整"]: 
        reply_text = f"日程調整ページはこちらです\n{base_url}/"
    else:
        reply_text = "日程調整を始める場合は「日調」または「日程調整」と送信してください。"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )


@app.route('/create', methods=['POST'])
def create_event():
    data = request.json
    event_id = str(uuid.uuid4())
    data["responses"] = [] 
    events[event_id] = data

    base_url = os.getenv("BASE_URL")

    if base_url and not base_url.endswith('/'):
        base_url += '/'
    member_page_url = base_url + 'event/' + event_id

    if user_id:
        try:
            msg = TextSendMessage(text=f"📅 新しい日程調整が作成されました！\n\n回答はこちら\n{member_page_url}")
            line_bot_api.push_message(user_id, msg)
            print("✅ LINEにプッシュ通知を送信しました。")
        except Exception as e:
            print("❌ LINE通知エラー:", e)
    else:
        print("⚠️ ユーザーID未登録のため、LINE通知はスキップ。")

    return jsonify({"status": "success", "url": member_page_url})

@app.route('/event/<event_id>')
def show_member_page(event_id):
    event_data = events.get(event_id)
    if not event_data:
        return "指定されたイベントが見つかりません。", 404
    return render_template('member_page.html', event_info=event_data)

@app.route('/submit/<event_id>', methods=['POST'])
def submit_response(event_id):
    event_data = events.get(event_id)
    if not event_data:
        return "イベントが見つかりません。", 404

    name = request.form.get("user_name")
    answers = []
    for key, value in request.form.items():
        if key.startswith("schedule"):
            answers.append(value)

    if "responses" not in event_data:
        event_data["responses"] = []
        
    event_data["responses"].append({
        "name": name,
        "answers": answers
    })

    print(f" {name} さんの回答を保存しました。")

    base_url = os.getenv("BASE_URL") 
    result_page_url = base_url + 'result/' + event_id

    if user_id:
        try:
            msg = TextSendMessage(text=f"✅ {name} さんが日程を提出しました！\n\n集計ページはこちら\n{result_page_url}")
            line_bot_api.push_message(user_id, msg)
        except Exception as e:
            print("LINE通知エラー:", e)

    return redirect(url_for('show_result_page', event_id=event_id))


@app.route('/result/<event_id>')
def show_result_page(event_id):
    event_data = events.get(event_id)
    if not event_data:
        return "イベントが見つかりません。", 404

    if not event_data.get("responses"):
        return "まだ誰も回答していません。"
    
    time_slots = []
    try:
        start_date_obj = datetime.strptime(event_data['startDate'], '%Y-%m-%d')
        end_date_obj = datetime.strptime(event_data['endDate'], '%Y-%m-%d')
        current_date_obj = start_date_obj
        duration = int(event_data['duration']) 
        is_exclude_enabled = event_data.get('isExcludeEnabled', False)
        exclude_start = int(event_data.get('excludeStart', -1))
        exclude_end = int(event_data.get('excludeEnd', -1))
        weekday_start = int(event_data['weekdayStart'])
        weekday_end = int(event_data['weekdayEnd'])
        holiday_start = int(event_data['holidayStart'])
        holiday_end = int(event_data['holidayEnd'])

        while current_date_obj <= end_date_obj:
            day_of_week = current_date_obj.weekday() 
            
            start_hour, end_hour = (holiday_start, holiday_end) if day_of_week >= 5 else (weekday_start, weekday_end)

            for hour in range(start_hour, end_hour, duration):
                slot_start = hour
                slot_end = hour + duration
                if slot_end > end_hour: continue

                if is_exclude_enabled and slot_start < exclude_end and slot_end > exclude_start:
                    continue
                
                weekdays_jp = ["月", "火", "水", "木", "金", "土", "日"]
                formatted_date = f"{current_date_obj.month}/{current_date_obj.day} ({weekdays_jp[day_of_week]})"
                time_slots.append(f"{formatted_date} {slot_start}:00-{slot_end}:00")
            
            current_date_obj += timedelta(days=1)
            
    except Exception as e:
        print(f"時間割生成エラー: {e}")
        return "イベントデータの解析中にエラーが発生しました。"

    total_slots = len(time_slots)
    counts = [{"ok": 0, "maybe": 0, "no": 0} for _ in range(total_slots)]
    for resp in event_data["responses"]:
        if len(resp.get("answers", [])) != total_slots:
            print(f"警告: {resp.get('name', '不明')}さんの回答数が一致しません。({len(resp.get('answers', []))} vs {total_slots})")
            continue 

        for i, ans in enumerate(resp["answers"]):
            if i < total_slots: 
                if ans == "〇": counts[i]["ok"] += 1
                elif ans == "△": counts[i]["maybe"] += 1
                elif ans == "✕": counts[i]["no"] += 1

    return render_template("result_page.html",
                           event_info=event_data,
                           counts=counts,
                           time_slots=time_slots, 
                           total_members=len(event_data["responses"]))
# --- 修正後 ---
if __name__ == '__main__':
    # host='0.0.0.0' は「どこからでも接続OK」、port=5001 は「5001番を使う」という意味です
    app.run(debug=True, host='0.0.0.0', port=5001)