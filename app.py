import time
import threading
import psutil
import json
import re
from flask import Flask, render_template, jsonify, request
from gpiozero import OutputDevice
import board
import adafruit_dht
import google.generativeai as genai

API_KEY = "API키 삽입"

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash-lite')

for proc in psutil.process_iter(['pid', 'name']):
    if proc.info['name'] and "libgpiod" in proc.info['name']:
        try:
            proc.kill()
        except:
            pass

DHT_PIN = board.D17
FAN_PIN = 22
HEATER_PIN = 27
LAMP_PIN = 26
HUMIDIFIER_PIN = 23

TARGET_TEMP = 26.0
TARGET_HUMID = 50.0

app = Flask(__name__)

fan = OutputDevice(FAN_PIN, active_high=True, initial_value=False)
heater = OutputDevice(HEATER_PIN, active_high=True, initial_value=False)
lamp = OutputDevice(LAMP_PIN, active_high=True, initial_value=False)
humidifier = OutputDevice(HUMIDIFIER_PIN, active_high=True, initial_value=False)

try:
    dht_device = adafruit_dht.DHT11(DHT_PIN, use_pulseio=False)
except:
    dht_device = None

current_data = {"temp": 0, "humid": 0, "mode": "AUTO"}

def ask_gemini(user_text):
    system_prompt = f"""
    너는 라즈베리파이 스마트홈 AI 비서야.
    현재 실내 온도는 {current_data['temp']}도, 습도는 {current_data['humid']}%야.
    
    사용자의 말을 듣고 다음 **JSON 형식**으로만 정확하게 답변해.
    마크다운(```json)이나 다른 설명은 절대 붙이지 마. 오직 순수 JSON만 줘.
    
    {{
        "action": "제어명령",
        "msg": "사용자에게 할 친절한 답변"
    }}

    [제어명령 목록]
    - 전등 켜기: LAMP_ON
    - 전등 끄기: LAMP_OFF
    - 에어컨 켜기: FAN_ON
    - 에어컨 끄기: FAN_OFF
    - 난방기 켜기: HEAT_ON
    - 난방기 끄기: HEAT_OFF
    - 가습기 켜기: HUM_ON
    - 가습기 끄기: HUM_OFF
    - 자동모드: AUTO_MODE
    - 수동모드: MANUAL_MODE
    - 제어 없음: NONE (그냥 대화할 때)

    예시: "불 켜줘" -> {{"action": "LAMP_ON", "msg": "네, 전등을 켜드릴게요!"}}
    """

    try:
        full_prompt = f"{system_prompt}\n\n사용자: {user_text}"
        response = model.generate_content(full_prompt)
        
        clean_text = response.text.strip()
        clean_text = re.sub(r"^```json\s*", "", clean_text)
        clean_text = re.sub(r"^```\s*", "", clean_text)
        clean_text = re.sub(r"\s*```$", "", clean_text)
        
        ai_data = json.loads(clean_text)
        return ai_data

    except Exception as e:
        print(f"Gemini 오류: {e}")
        return {"action": "NONE", "msg": "죄송해요, AI 서버와 통신이 원활하지 않아요."}

def process_ai_command(ai_data):
    action = ai_data.get("action", "NONE")
    msg = ai_data.get("msg", "")

    print(f"Gemini 판단: {action} / 답변: {msg}")

    if action == "LAMP_ON": lamp.on()
    elif action == "LAMP_OFF": lamp.off()
    
    elif action == "FAN_ON":
        current_data["mode"] = "MANUAL"
        fan.on(); heater.off()
    elif action == "FAN_OFF":
        current_data["mode"] = "MANUAL"
        fan.off()
        
    elif action == "HEAT_ON":
        current_data["mode"] = "MANUAL"
        heater.on(); fan.off()
    elif action == "HEAT_OFF":
        current_data["mode"] = "MANUAL"
        heater.off()
        
    elif action == "HUM_ON":
        current_data["mode"] = "MANUAL"
        humidifier.on()
    elif action == "HUM_OFF":
        current_data["mode"] = "MANUAL"
        humidifier.off()
        
    elif action == "AUTO_MODE": current_data["mode"] = "AUTO"
    elif action == "MANUAL_MODE": current_data["mode"] = "MANUAL"

    return msg

def automation_loop():
    print("스마트홈 자동화 시스템 가동 중...")
    while True:
        try:
            if dht_device:
                try:
                    t = dht_device.temperature
                    h = dht_device.humidity
                    if t is not None and h is not None:
                        current_data["temp"] = round(t, 1)
                        current_data["humid"] = round(h, 1)
                except RuntimeError:
                    pass
            
            if current_data["mode"] == "AUTO":
                curr_t = current_data["temp"]
                curr_h = current_data["humid"]
                if curr_t != 0: 
                    if curr_t > TARGET_TEMP + 1.0: 
                        if not fan.value: fan.on(); heater.off()
                    elif curr_t < TARGET_TEMP - 1.0: 
                        if not heater.value: fan.off(); heater.on()
                    else: 
                        if fan.value or heater.value: fan.off(); heater.off()

                    if curr_h < TARGET_HUMID - 5.0:
                        if not humidifier.value: humidifier.on()
                    elif curr_h >= TARGET_HUMID:
                        if humidifier.value: humidifier.off()
            
            time.sleep(2)
        except Exception as e:
            print(f"Auto Loop Error: {e}")
            time.sleep(2)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/status')
def status():
    return jsonify({
        "temp": current_data["temp"],
        "humid": current_data["humid"],
        "fan": fan.value,
        "heater": heater.value,
        "lamp": lamp.value,
        "humidifier": humidifier.value,
        "mode": current_data["mode"]
    })

@app.route('/control', methods=['POST'])
def control():
    action = request.form.get('action')
    if action == "auto_toggle":
        current_data["mode"] = "MANUAL" if current_data["mode"] == "AUTO" else "AUTO"
        fan.off(); heater.off(); humidifier.off()
    elif action == "lamp_toggle": lamp.toggle()
    elif current_data["mode"] == "MANUAL":
        if action == "fan_toggle": fan.toggle()
        elif action == "heater_toggle": heater.toggle()
        elif action == "humidifier_toggle": humidifier.toggle()
    return "OK"

@app.route('/chat', methods=['POST'])
def chat():
    user_msg = request.form.get('msg')
    
    ai_data = ask_gemini(user_msg)
    
    final_response = process_ai_command(ai_data)
    
    return jsonify({"response": final_response})

if __name__ == '__main__':
    t_auto = threading.Thread(target=automation_loop)
    t_auto.daemon = True
    t_auto.start()

    app.run(host='0.0.0.0', port=5000, debug=False)