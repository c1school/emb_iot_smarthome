import time
import threading
import psutil
from flask import Flask, render_template, jsonify, request
from gpiozero import OutputDevice
import board
import adafruit_dht
import speech_recognition as sr
from ctypes import * # --- [1. ALSA 에러 메시지 숨기기] ---
ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)
def py_error_handler(filename, line, function, err, fmt):
    pass
c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)
asound = cdll.LoadLibrary('libasound.so')
asound.snd_lib_error_set_handler(c_error_handler)

# --- [2. GPIO Busy 에러 방지] ---
for proc in psutil.process_iter(['pid', 'name']):
    if proc.info['name'] and "libgpiod" in proc.info['name']:
        try:
            proc.kill()
        except:
            pass

# --- [3. 핀 번호 설정] ---
DHT_PIN = board.D17       # 온습도 센서
FAN_PIN = 22              # 에어컨 (파란 LED)
HEATER_PIN = 27           # 난방기 (빨간 LED)
LAMP_PIN = 26             # 전등 (노란 LED)
HUMIDIFIER_PIN = 23       # [NEW] 가습기 (초록 LED 추천)

TARGET_TEMP = 26.0        # 희망 온도
TARGET_HUMID = 50.0       # [NEW] 희망 습도

# --- [4. 기기 초기화] ---
app = Flask(__name__)

# LED(가전제품) 설정
fan = OutputDevice(FAN_PIN, active_high=True, initial_value=False)
heater = OutputDevice(HEATER_PIN, active_high=True, initial_value=False)
lamp = OutputDevice(LAMP_PIN, active_high=True, initial_value=False)
humidifier = OutputDevice(HUMIDIFIER_PIN, active_high=True, initial_value=False) # [NEW]

# 온습도 센서 설정
try:
    dht_device = adafruit_dht.DHT11(DHT_PIN, use_pulseio=False)
except:
    dht_device = None

# 상태 저장소
current_data = {
    "temp": 0, "humid": 0, "mode": "AUTO"
}

# --- [5. 자동화 로직 (스레드 1)] ---
def automation_loop():
    print("🤖 스마트홈 자동화 시스템 가동 중...")
    while True:
        try:
            # 센서 읽기
            if dht_device:
                try:
                    t = dht_device.temperature
                    h = dht_device.humidity
                    if t is not None and h is not None:
                        current_data["temp"] = round(t, 1)
                        current_data["humid"] = round(h, 1)
                except RuntimeError:
                    pass
            
            # [자동 제어 로직]
            if current_data["mode"] == "AUTO":
                curr_t = current_data["temp"]
                curr_h = current_data["humid"]
                
                if curr_t != 0: 
                    # 1. 온도 제어 (에어컨/히터)
                    if curr_t > TARGET_TEMP + 1.0: # 더울 때
                        if not fan.value: fan.on(); heater.off()
                    elif curr_t < TARGET_TEMP - 1.0: # 추울 때
                        if not heater.value: fan.off(); heater.on()
                    else: # 쾌적
                        if fan.value or heater.value: fan.off(); heater.off()

                    # 2. 습도 제어 (가습기) [NEW]
                    # 습도가 목표보다 5% 이상 낮으면(건조하면) 가습기 ON
                    if curr_h < TARGET_HUMID - 5.0:
                        if not humidifier.value: humidifier.on()
                    # 습도가 목표 이상이면 가습기 OFF
                    elif curr_h >= TARGET_HUMID:
                        if humidifier.value: humidifier.off()
            
            time.sleep(2)
        except Exception as e:
            print(f"Auto Loop Error: {e}")
            time.sleep(1)

# --- [6. 음성 인식 로직 (스레드 2)] ---
def voice_loop():
    while True:
        try:
            r = sr.Recognizer()
            mic = sr.Microphone()
            print("🎤 마이크 연결 시도 중...")
            with mic as source:
                r.adjust_for_ambient_noise(source, duration=1)
                print("🎤 음성 인식 준비 완료!")
                
                while True:
                    try:
                        audio = r.listen(source, timeout=5, phrase_time_limit=3)
                        text = r.recognize_google(audio, language='ko-KR')
                        print(f"🗣️ 인식된 명령: {text}")
                        process_voice_command(text)
                    except sr.WaitTimeoutError: pass
                    except sr.UnknownValueError: print("❌ 발음 불명확")
                    except OSError: break # 재연결 트리거
                    except Exception as e:
                        if "Stream closed" in str(e): break

        except Exception:
            time.sleep(3)

def process_voice_command(text):
    text = text.replace(" ", "")
    
    # 1. 전등
    if "전등" in text or "불" in text:
        if "켜" in text: lamp.on()
        elif "꺼" in text: lamp.off()

    # 2. 에어컨
    elif "에어컨" in text:
        current_data["mode"] = "MANUAL"
        if "켜" in text: fan.on(); heater.off()
        elif "꺼" in text: fan.off()

    # 3. 난방기
    elif "난방" in text or "히터" in text:
        current_data["mode"] = "MANUAL"
        if "켜" in text: heater.on(); fan.off()
        elif "꺼" in text: heater.off()

    # 4. 가습기 [NEW]
    elif "가습" in text:
        current_data["mode"] = "MANUAL"
        if "켜" in text: humidifier.on()
        elif "꺼" in text: humidifier.off()
            
    # 5. 모드
    elif "자동" in text and "모드" in text:
        current_data["mode"] = "AUTO"
    elif "수동" in text and "모드" in text:
        current_data["mode"] = "MANUAL"

# --- [7. 웹 서버] ---
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
        "humidifier": humidifier.value, # [NEW]
        "mode": current_data["mode"]
    })

@app.route('/control', methods=['POST'])
def control():
    action = request.form.get('action')
    
    if action == "auto_toggle":
        current_data["mode"] = "MANUAL" if current_data["mode"] == "AUTO" else "AUTO"
        fan.off(); heater.off(); humidifier.off()
    
    elif action == "lamp_toggle":
        lamp.toggle()

    elif current_data["mode"] == "MANUAL":
        if action == "fan_toggle": fan.toggle()
        elif action == "heater_toggle": heater.toggle()
        elif action == "humidifier_toggle": humidifier.toggle() # [NEW]
            
    return "OK"

if __name__ == '__main__':
    t_auto = threading.Thread(target=automation_loop)
    t_auto.daemon = True
    t_auto.start()

    t_voice = threading.Thread(target=voice_loop)
    t_voice.daemon = True
    t_voice.start()

    app.run(host='0.0.0.0', port=5000, debug=False)