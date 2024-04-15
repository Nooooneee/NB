from flask import Flask, flash, redirect, send_from_directory, url_for, render_template, session, request, jsonify
from config import Config
from flask_mysqldb import MySQL
from utils import save_image, allowed_file, fc_load_model, predict_image, get_data_from_db, add_user_to_db, validate_login, calculate_nutrient_totals
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
            flash('검색된 음식이 없습니다.', 'warning')
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
        flash("로그인이 필요한 기능입니다.", "info")
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
        flash("음식이 성공적으로 추가되었습니다.", "success")

    except Exception as e:
        mysql.connection.rollback()
        flash("음식 추가에 실패하였습니다: " + str(e), "danger")
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
    flash('성공적으로 로그아웃하였습니다.', 'success')
    return redirect(url_for('login'))


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
                flash('회원가입이 성공적으로 완료되었습니다.', 'success')
                return redirect(url_for('login'))
            else:
                mysql.connection.rollback()  # 오류 발생 시 변경사항 롤백
                flash('회원가입에 실패했습니다. 다시 시도해주세요.', 'danger')
                return redirect(url_for('signup'))

        except Exception as e:
            mysql.connection.rollback()  # 오류 발생 시 변경사항 롤백
            flash(f'오류 발생: {str(e)}', 'danger')
            return redirect(url_for('signup'))

        finally:
            cursor.close()  # 커서 닫기

    return render_template('signup.html')

from datetime import datetime

@app.route('/nutrition', methods=['GET', 'POST'])
def nutrition():
    if 'username' not in session:
        # 사용자가 로그인하지 않았으면 로그인 페이지로 리디렉션
        flash("로그인이 필요합니다.", "info")
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
        flash("로그인이 필요합니다.", "info")
        return redirect(url_for('login'))

    username = session['username']
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    today_date = datetime.today().strftime('%Y-%m-%d')
    selected_date = request.args.get('date', today_date)

    query = """
            SELECT SUM(food_info_2.kcal) AS kcal, SUM(food_info_2.carbohydrate) AS carbohydrate, SUM(food_info_2.protein) AS protein, SUM(food_info_2.fat) AS fat, SUM(food_info_2.sugars) AS sugars, SUM(food_info_2.salt) AS salt, SUM(food_info_2.coles) AS coles, SUM(food_info_2.mag) AS mag, SUM(food_info_2.calcium) AS calcium, SUM(food_info_2.iron) AS iron
            FROM user_food_intake
            JOIN food_info_2 ON user_food_intake.food_name = food_info_2.name
            WHERE user_food_intake.user_id = %s AND DATE(user_food_intake.created_at) = %s
            """
    cursor.execute(query, (username, selected_date))
    current_intake = cursor.fetchone()

    # Map English keys to Korean for display in the template
    if current_intake:
        current_intake = {Config.nutrient_map[key]: value for key, value in current_intake.items() if key in Config.nutrient_map}

    cursor.close()
    return render_template('recommendation.html', date=selected_date, current_intake=current_intake)


if __name__ == '__main__':
    app.run(debug=True)
