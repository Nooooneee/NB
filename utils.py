from werkzeug.utils import secure_filename
from PIL import Image
import os
from tensorflow.keras.preprocessing import image
from tensorflow.keras.models import load_model
import numpy as np
from flask import flash
from werkzeug.security import check_password_hash, generate_password_hash
import MySQLdb


def fc_load_model(model_path):
    # 모델 구조와 가중치를 로드합니다.
    model = load_model(model_path)
    return model


def prepare_image(image_path):
    img = image.load_img(image_path, target_size=(188, 188))  # 이미지 크기 조정
    img_array = image.img_to_array(img)  # 이미지를 배열로 변환
    img_array_expanded_dims = np.expand_dims(img_array, axis=0)  # 배치 차원 추가
    img_array_expanded_dims /= 255.
    return img_array_expanded_dims  # 모델에 맞는 전처리 수행

def predict_image(model, image_path):
    processed_image = prepare_image(image_path)
    predictions = model.predict(processed_image)
    #print(predictions)
    # 여기서는 가장 높은 확률을 가진 클래스의 인덱스를 반환합니다.
    # 실제 애플리케이션에 따라 결과 처리 방법을 변경해야 할 수 있습니다.
    return np.argmax(predictions)


def allowed_file(filename, allowed_extensions):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

def save_image(file, upload_folder, allowed_extensions, specific_size):
    if file and allowed_file(file.filename, allowed_extensions):
        filename = secure_filename(file.filename)
        file_path = os.path.join(upload_folder, filename)
        file.save(file_path)
        if not is_specific_image_size(file_path, specific_size):
            #os.remove(file_path)  # 지정된 사이즈가 아니면 파일 삭제
            return None
        return filename
    return None

def is_specific_image_size(image_path, specific_size):
    with Image.open(image_path) as img:
        return True #img.size == specific_size

def get_data_from_db(food_name, mysql):
    cursor = mysql.connection.cursor()
    # 여기서 `your_table_name`은 실제 테이블 이름으로 대체해야 함
    cursor.execute("SELECT * FROM food_info_2 WHERE name = %s", [food_name])
    data = cursor.fetchall()
    cursor.close()
    return data

def add_user_to_db(cursor, username, password, email, weight, target_weight, gender):
    hashed_password = generate_password_hash(password)
    try:
        cursor.execute('''INSERT INTO users (username, pass, email, weight, target_weight, gender) 
                          VALUES (%s, %s, %s, %s, %s, %s)''',
                       (username, hashed_password, email, weight, target_weight, gender))
        return True
    except MySQLdb._exceptions.IntegrityError as e:
        flash('이미 사용중인 사용자 이름이나 이메일입니다.', 'danger')
        return False

def validate_login(cursor, username, password):
    cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
    account = cursor.fetchone()
    if account and check_password_hash(account['pass'], password):
        return account
    else:
        return None

def search_food(cursor, foodname):
    cursor.execute('SELECT * FROM food_info_2 WHERE name = %s', (foodname,))
    search_results = cursor.fetchone()
    if search_results:
        return search_results
    else:
        return None

def calculate_nutrient_totals(food_intakes, cursor):
    RDA = {'kcal': 2500, 'carbohydrate': 320, 'protein': 52.5, 'fat': 44.5,
           'sugars': 25, 'salt': 2000, 'coles': 300, 'mag': 315, 'calcium': 700, 'iron': 12}
    nutrient_sums = {key: 0 for key in RDA}  # Initialize sums

    for intake in food_intakes:
        cursor.execute('SELECT * FROM food_info_2 WHERE name = %s', (intake['food_name'],))
        food_info = cursor.fetchone()
        if food_info:
            for nutrient, value in food_info.items():
                if nutrient in nutrient_sums:
                    nutrient_sums[nutrient] += value

    nutrient_totals = []
    for nutrient, total in nutrient_sums.items():
        percent = (total / RDA[nutrient] * 100) if RDA[nutrient] != 0 else 0
        nutrient_totals.append({'name': nutrient, 'percent': round(percent)})
    nutrient_map = {
        'kcal': '칼로리',
        'carbohydrate': '탄수화물',
        'protein': '단백질',
        'fat': '지방',
        'sugars': '설탕',
        'salt': '나트륨',
        'coles': '콜레스테롤',
        'mag': '마그네슘',
        'calcium': '칼슘',
        'iron': '철'
    }
    for nutrient in nutrient_totals:
        nutrient['korean_name'] = nutrient_map[nutrient['name']]
    return nutrient_totals