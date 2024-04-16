import copy

from flask import Flask, flash, redirect, send_from_directory, url_for, render_template, session, request, jsonify
from config import Config
from flask_mysqldb import MySQL
from utils import save_image, allowed_file, fc_load_model, predict_image, get_data_from_db, add_user_to_db, validate_login, calculate_nutrient_totals, get_current_intake, calculate_deficiencies, find_closest_food_with_nutrients
import os
import MySQLdb.cursors
import pandas as pd
import numpy as np
import logging

stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.DEBUG)


app = Flask(__name__)
app.config.from_object(Config)
# MySQL 설정
mysql = MySQL(app)

app.logger.addHandler(stream_handler)

# Windows 환경에서의 상대 경로 설정
app.config['UPLOAD_FOLDER'] = './static/uploads'
model = fc_load_model(Config.MODEL_PATH)

# zip 함수를 Jinja 환경의 전역 변수로 추가
app.jinja_env.globals.update(zip=zip)


@app.route('/')
def home():
    return render_template('home.html')

@app.route('/search', methods=['GET', 'POST'])
def search():
    if request.method == 'POST':
        food_name = request.form['food_name']
        data = get_data_from_db(food_name, mysql)
        if data:
            data_dict = data[0]  # 데이터가 있으면 첫 번째 결과를 사용
            return render_template('search_result.html', data=data_dict, RDA=Config.RDA)
        else:
            return redirect(url_for('search'))
    return render_template('search.html')


@app.route('/autocomplete', methods=['GET'])
def autocomplete():
    search = request.args.get('term')
    cursor = mysql.connection.cursor()
    query = f"SELECT name FROM food_info_2 WHERE name LIKE '%{search}%' LIMIT 5"
    cursor.execute(query)
    results = cursor.fetchall()
    suggestions = [result['name'] for result in results]
    return jsonify(suggestions)



@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        file = request.files.get('file')
        if file and allowed_file(file.filename, app.config['ALLOWED_EXTENSIONS']):
            filename = save_image(file, app.config['UPLOAD_FOLDER'], app.config['ALLOWED_EXTENSIONS'], app.config['SPECIFIC_IMAGE_SIZE'])
            if filename:
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                image_size = os.path.getsize(file_path)
                image_url = url_for('static', filename='uploads/' + filename)
                prediction = predict_image(model, file_path)
                prediction = int(prediction)
                prediction = Config.category[prediction][1]
                data = get_data_from_db(prediction, mysql)
                data_dict = data[0] if data else {}
                return render_template('image_display.html', prediction=prediction, image_url=image_url, filename=filename, image_size=image_size, data=data_dict, RDA=Config.RDA)
            else:
                flash(f'Image must be exactly {app.config["SPECIFIC_IMAGE_SIZE"][0]}x{app.config["SPECIFIC_IMAGE_SIZE"][1]} pixels')
        else:
            flash('Invalid file or file type')
        return redirect('/upload')
    return render_template('upload_form.html')

@app.route('/add_food', methods=['POST'])
def add_food():
    if 'loggedin' not in session:
        # 사용자가 로그인하지 않은 경우 로그인 페이지로 리디렉션
        return redirect(url_for('login'))

    user_id = session['username']  # 세션에서 사용자 ID 가져오기
    food_name = request.form['food_name']  # 폼 데이터에서 음식 이름 가져오기
    print(user_id)
    cursor = mysql.connection.cursor()
    try:
        # user_food_intake 테이블에 음식 이름 추가
        insert_query = "INSERT INTO user_food_intake (user_id, food_name) VALUES (%s, %s)"
        cursor.execute(insert_query, (user_id, food_name))
        mysql.connection.commit()

    except Exception as e:
        mysql.connection.rollback()
    finally:
        cursor.close()
    return redirect(url_for('nutrition'))  # 성공적으로 추가 후 리디렉션할 페이지

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        account = validate_login(cursor, username, password)

        if account:
            session['loggedin'] = True
            session['username'] = account['username']
            return redirect('/upload')
        else:
            flash('로그인 실패: 사용자 이름이나 비밀번호가 잘못되었습니다.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('loggedin', None)
    session.pop('username', None)
    return redirect(url_for('home'))


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        # 폼 데이터 받기
        username = request.form.get('username')
        password = request.form.get('password')
        email = request.form.get('email')
        weight = request.form.get('weight')
        target_weight = request.form.get('target_weight')
        gender = request.form.get('gender')

        cursor = mysql.connection.cursor()

        try:
            success = add_user_to_db(cursor, username, password, email, weight, target_weight, gender)

            if success:
                mysql.connection.commit()  # 변경사항 저장
                return redirect(url_for('login'))
            else:
                mysql.connection.rollback()  # 오류 발생 시 변경사항 롤백
                return redirect(url_for('signup'))

        except Exception as e:
            mysql.connection.rollback()  # 오류 발생 시 변경사항 롤백
            return redirect(url_for('signup'))

        finally:
            cursor.close()  # 커서 닫기

    return render_template('signup.html')

from datetime import datetime

@app.route('/nutrition', methods=['GET', 'POST'])
def nutrition():
    if 'username' not in session:
        # 사용자가 로그인하지 않았으면 로그인 페이지로 리디렉션
        return redirect(url_for('login'))

    # 로그인된 사용자의 ID를 조회
    username = session['username']
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # 기본적으로 오늘 날짜 선택, 사용자가 다른 날짜를 선택했을 때는 해당 날짜의 데이터를 가져옴
    today_date = datetime.today().strftime('%Y-%m-%d')
    selected_date = request.form.get('selected_date', today_date)
    query = "SELECT * FROM user_food_intake WHERE user_id = %s AND DATE(created_at) = %s"
    cursor.execute(query, (username, selected_date))
    food_intakes = cursor.fetchall()

    nutrient_totals = calculate_nutrient_totals(food_intakes, cursor)

    cursor.close()

    return render_template('nutrition.html', food_intakes=food_intakes, selected_date=selected_date, nutrient_totals=nutrient_totals)


@app.route('/delete_food_intake', methods=['POST'])
def delete_food_intake():
    if 'loggedin' not in session:
        return jsonify({'success': False, 'error': '로그인이 필요합니다.'}), 403

    data = request.get_json()
    intake_id = data.get('intake_id')
    cursor = mysql.connection.cursor()
    try:
        cursor.execute('DELETE FROM user_food_intake WHERE id = %s', (intake_id,))
        mysql.connection.commit()
        return jsonify({'success': True}), 200
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()

@app.route('/recommendation', methods=['GET', 'POST'])
def recommendation():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # 사용자의 현재 섭취량 가져오기
    current_intake = get_current_intake(username, cursor)
    # 가장 부족한 영양소 계산
    nutrient_deficiencies = calculate_deficiencies(current_intake, Config.RDA2)

    # 부족량에 가장 가까운 음식 찾기
    closest_food, food_nutrients = find_closest_food_with_nutrients(nutrient_deficiencies, cursor)

    cursor.execute("SELECT * FROM food_info_2 WHERE name = %s", (closest_food,))
    food_nutrients = cursor.fetchone()
    current_intake_origin = copy.copy(current_intake)
    if food_nutrients:
        # 영양분을 현재 섭취량에 더하기
        for nutrient, value in food_nutrients.items():
            if nutrient in current_intake and value is not None:
                current_intake[nutrient] = current_intake.get(nutrient, 0) + value
    print(current_intake_origin)
    print(current_intake)
    cursor.close()
    return render_template('recommendation.html', current_intake_origin=current_intake_origin, current_intake=current_intake, closest_food=closest_food, Config=Config)


if __name__ == '__main__':
    app.run(debug=True)
