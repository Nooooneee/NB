from flask import Flask, flash, redirect, send_from_directory, url_for, render_template, session, request, jsonify
from config import Config
from flask_mysqldb import MySQL
from utils import save_image, allowed_file, fc_load_model, predict_image, get_data_from_db, add_user_to_db, validate_login, search_food
import os
import MySQLdb.cursors

app = Flask(__name__)
app.config.from_object(Config)
# MySQL 설정
mysql = MySQL(app)

# Windows 환경에서의 상대 경로 설정
app.config['UPLOAD_FOLDER'] = './static/uploads'
model = fc_load_model(Config.MODEL_PATH)

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/search', methods=['GET', 'POST'])
def search():
    if request.method == 'POST':
        pass
    # 음식 검색 기능을 처리하는 코드
    return render_template('search.html')


@app.route('/autocomplete', methods=['GET'])
def autocomplete():
    name = request.args.get('term')
    cursor = mysql.connection.cursor()
    try:
        success = search_food(cursor, name)

        if success:
            return jsonify(success)
        else:
            return None
    finally:
        cursor.close()  # 커서 닫기


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


if __name__ == '__main__':
    app.run(debug=True)
