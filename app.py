import os
import logging
from datetime import datetime
from flask import flash, redirect, url_for
import pyodbc
from flask import (
    Flask, request, jsonify, render_template,
    session, redirect, url_for
)

# ----- Настройка логирования -----
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO  
)
logger = logging.getLogger(__name__)

db_server = ""
db_port = ""
db_name = ""
db_user = ""
db_password = ""

app = Flask(__name__)
app.secret_key = "Eo9HC!Dk39Q0XyF2uB^#hLzv"

def connect_to_db():
    try:
        conn = pyodbc.connect(
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={db_server},{db_port};"
            f"DATABASE={db_name};"
            f"UID={db_user};"
            f"PWD={db_password};"
            f"TrustServerCertificate=yes;"
        )
        return conn
    except Exception as e:
        logger.exception("Ошибка при подключении к базе данных:")
        return None

@app.route('/priemka', methods=['GET'])
def priemka():
    if 'who' not in session:
        return redirect(url_for('login'))
    return render_template('priemka.html')


@app.route('/')
def home():
    # Редирект на логин
    return redirect('/login')

@app.route('/main', methods=['GET'])
def main_menu():
    if 'who' not in session:
        return redirect(url_for('login'))
    return render_template('main_menu.html')


@app.route('/priemka/submit', methods=['POST'])
def priemka_submit():
    if 'who' not in session:
        return jsonify({'status': 'error', 'message': 'Не авторизован'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'No JSON data'}), 400

    code         = data.get('code')
    user_doc_id  = data.get('delivery_id')  # номер поставки, введённый пользователем
    user_box_num = data.get('box_num')      # номер коробки, введённый пользователем

    if not code:
        return jsonify({'status': 'error', 'message': 'No code provided'}), 400
    if not user_doc_id or not user_box_num:
        return jsonify({'status': 'error', 'message': 'Не указаны поставка или коробка!'}), 400

    who = session.get('who', 'UNKNOWN')

    conn = connect_to_db()
    if not conn:
        return jsonify({'status': 'error', 'message': 'DB connection failed'}), 500

    try:
        cursor = conn.cursor()

        # 1) Ищем код в DITE_CM_GTIN_Codes_v2
        cursor.execute("""
            SELECT ID, ID_Documents, CasesNum
            FROM DITE_CM_GTIN_Codes_v2
            WHERE Codes = ?
        """, (code,))
        row_v2 = cursor.fetchone()
        if not row_v2:
            # Если хотим также искать в старой DITE_CM_GTIN_Codes:
            cursor.execute("""
                SELECT ID
                FROM DITE_CM_GTIN_Codes
                WHERE Codes = ?
            """, (code,))
            row_old = cursor.fetchone()
            if not row_old:
                return jsonify({
                    'status': 'error',
                    'message': 'Честный знак не найден ни в DITE_CM_GTIN_Codes_v2, ни в DITE_CM_GTIN_Codes!'
                }), 400
            # Нашли в старой таблице
            found_in = 'old'
            id_codes = None
            doc_id   = None
            cases_num= None
        else:
            found_in = 'v2'
            id_codes  = row_v2[0]  # PK
            doc_id    = row_v2[1]  # ID_Documents (номер поставки в базе)
            cases_num = row_v2[2]  # CasesNum (номер коробки в базе)

        # 2) Сравниваем doc_id и cases_num с тем, что ввёл пользователь
        #    Нужно, чтобы str(doc_id) == user_doc_id, str(cases_num) == user_box_num
        if doc_id is None or cases_num is None:
            return jsonify({
                'status': 'error',
                'message': 'В базе нет данных о поставке/коробке (старый код?).'
            }), 400

        if str(doc_id) != str(user_doc_id):
            return jsonify({
                'status': 'error',
                'message': 'Товар принадлежит другой поставке!'
            }), 400

        if str(cases_num) != str(user_box_num):
            return jsonify({
                'status': 'error',
                'message': 'Товар принадлежит другой коробке!'
            }), 400

        # 3) Проверяем, не сканировали ли уже этот код (для данной поставки/коробки)
        #    Поскольку мы не используем ID_Case, будем считать, что "уже сканировали",
        #    если NumCase=user_box_num и ID_DeliveriesMP=user_doc_id.
        cursor.execute("""
            SELECT ID
            FROM DITE_Deliveries_MPScans
            WHERE ID_Product = ?
              AND NumCase = ?
              AND ID_DeliveriesMP = ?
        """, (code, user_box_num, user_doc_id))
        row_scanned = cursor.fetchone()
        if row_scanned:
            return jsonify({
                'status': 'error',
                'message': 'Этот честный знак уже отсканирован для данной поставки/коробки!'
            }), 400

        # 4) Вставляем запись:
        #    ID_Case = NULL, NumCase = user_box_num, ID_DeliveriesMP = user_doc_id
        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d')
        time_str = now.strftime('%H:%M:%S')

        cursor.execute("""
            INSERT INTO DITE_Deliveries_MPScans
            (ID_Case, NumCase, ID_DeliveriesMP, Who,
             DateScan, TimeScan, ID_Product, Scan_Status,
             ID_Codes)
            VALUES (NULL, ?, ?, ?, ?, ?, ?, 'OK', ?)
        """, (
            user_box_num,
            user_doc_id,
            who,
            date_str,
            time_str,
            code,
            id_codes
        ))

        conn.commit()
        return jsonify({
            'status': 'success',
            'message': f'Честный знак успешно принят (найден в {found_in})'
        }), 200

    except Exception as e:
        conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        conn.close()










# --------------------------
# 1) Роут для ЛОГИНА (с проверкой DITE_Logins)
# --------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')
    else:
        password = request.form.get('password')
        if not password:
            return "Введите пароль", 400

        conn = connect_to_db()
        if not conn:
            return "Ошибка подключения к БД", 500
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT Surname_N_LN 
                FROM DITE_Logins
                WHERE Password = ?
            """, (password,))
            row = cursor.fetchone()
            if row:
                # Сохраняем ФИО пользователя в сессии
                session['who'] = row[0]
                return redirect(url_for('main_menu'))
            else:
                return render_template('login.html', error="Неверный пароль")
        except Exception as e:
            logger.exception("Ошибка при авторизации:")
            return f"Ошибка: {e}", 500
        finally:
            conn.close()


# --------------------------
# 2) Роут для ввода номера поставки (delivery.html)
# --------------------------
@app.route('/delivery', methods=['GET', 'POST'])
def delivery():
    # Проверяем авторизацию
    if 'who' not in session:
        return redirect(url_for('login'))

    if request.method == 'GET':
        return render_template('delivery.html')
    else:
        code = request.form.get('delivery_id', '').strip()
        if not code:
            return "Введите номер поставки!", 400

        conn = connect_to_db()
        if not conn:
            return "Ошибка подключения к БД", 500

        try:
            cursor = conn.cursor()

            # Проверяем: есть ли дефис (значит InnerBarcode)
            if '-' in code:
                # ---- 1) Ищем в DITE_Deliveries_MPCase_v2 по InnerBarcode ----
                cursor.execute("""
                    SELECT ID, ID_DeliveriesMP, NumCase
                    FROM DITE_Deliveries_MPCase_v2
                    WHERE InnerBarcode = ?
                """, (code,))
                row_case = cursor.fetchone()
                if not row_case:
                    # Нет такой коробки
                    return render_template('delivery.html',
                        error="Штрихкод (InnerBarcode) не найден!"
                    )

                box_id            = row_case[0]  # ID коробки
                delivery_id_found = row_case[1]  # ID_DeliveriesMP (номер поставки)
                num_case          = row_case[2]

                # Сохраняем в сессию
                session['delivery_id'] = delivery_id_found

                # Перенаправляем сразу на сканирование этой коробки
                # (или можно на /box_contents/<box_id>, если хотите)
                return redirect(url_for('scan_box', box_id=box_id))

            else:
                # ---- 2) Нет дефиса => считаем это "номер поставки" ----
                cursor.execute("""
                    SELECT COUNT(*)
                    FROM DITE_Deliveries_MP_v2
                    WHERE ID = ?
                """, (code,))
                row = cursor.fetchone()
                if row[0] == 0:
                    # Поставки нет
                    return render_template('delivery.html',
                        error="Такой поставки не существует"
                    )

                # Сохраняем в сессию
                session['delivery_id'] = code

                # Перенаправляем на список коробок
                return redirect(url_for('boxes'))

        except Exception as e:
            logger.exception("Ошибка при проверке поставки/коробки:")
            return f"DB error: {e}", 500
        finally:
            conn.close()


# --------------------------
# 3) Список коробок (boxes.html)
# --------------------------
@app.route('/boxes', methods=['GET'])
def boxes():
    if 'who' not in session:
        return redirect(url_for('login'))

    delivery_id = session.get('delivery_id')
    if not delivery_id:
        return redirect(url_for('delivery'))

    conn = connect_to_db()
    if not conn:
        return "Ошибка подключения к БД", 500

    try:
        cursor = conn.cursor()
        # Получаем список коробок
        cursor.execute("""
            SELECT ID, NumCase
            FROM DITE_Deliveries_MPCase_v2
            WHERE ID_DeliveriesMP = ?
        """, (delivery_id,))
        rows = cursor.fetchall()

        boxes_list = []
        for r in rows:
            box_id = r[0]
            num_case = r[1]

            # Сколько всего
            cursor.execute("""
                SELECT SUM(Counts)
                FROM DITE_Deliveries_MPArticulsToTPositionsCase_v2
                WHERE ID_DeliveriesMP = ? AND ID_Case = ?
            """, (delivery_id, box_id))
            total_counts = cursor.fetchone()[0] or 0

            # Сколько отсканировано
            cursor.execute("""
                SELECT COUNT(*)
                FROM DITE_Deliveries_MPScans
                WHERE ID_Case = ? AND ID_DeliveriesMP = ?
            """, (box_id, delivery_id))
            scanned_count = cursor.fetchone()[0]

            boxes_list.append({
                'ID_Case': box_id,
                'NumCase': num_case,
                'Total': total_counts,
                'Scanned': scanned_count
            })
    except Exception as e:
        logger.exception("Ошибка при получении коробок:")
        return f"DB error: {e}", 500
    finally:
        conn.close()

    session['boxes_info'] = boxes_list
    return render_template('boxes.html',
                           delivery_id=delivery_id,
                           boxes=boxes_list)

# --------------------------
# 4) Просмотр/сканирование конкретной коробки (scan_box.html)
# --------------------------
@app.route('/scan_box/<int:box_id>', methods=['GET'])
def scan_box(box_id):
    if 'who' not in session:
        return redirect(url_for('login'))

    delivery_id = session.get('delivery_id')
    if not delivery_id:
        return redirect(url_for('delivery'))

    conn = connect_to_db()
    if not conn:
        return "Ошибка подключения к БД", 500

    try:
        cursor = conn.cursor()
        # Пример подсчёта "всего" и "сколько отсканировано":
        cursor.execute("""
            SELECT SUM(Counts)
            FROM DITE_Deliveries_MPArticulsToTPositionsCase_v2
            WHERE ID_DeliveriesMP = ? AND ID_Case = ?
        """, (delivery_id, box_id))
        total_required = cursor.fetchone()[0] or 0

        cursor.execute("""
            SELECT COUNT(*)
            FROM DITE_Deliveries_MPScans
            WHERE ID_Case = ? AND ID_DeliveriesMP = ?
        """, (box_id, delivery_id))
        scanned_count = cursor.fetchone()[0]

        # Узнаём NumCase
        cursor.execute("""
            SELECT NumCase
            FROM DITE_Deliveries_MPCase_v2
            WHERE ID = ?
        """, (box_id,))
        row = cursor.fetchone()
        num_case = row[0] if row else None

    except Exception as e:
        conn.rollback()
        logger.exception("Ошибка при загрузке данных коробки:")
        return f"DB error: {e}", 500
    finally:
        conn.close()

    return render_template(
        'scan_box.html',
        box_id=box_id,
        num_case=num_case,
        total_required=total_required,
        scanned_count=scanned_count,
        delivery_id=delivery_id  # <-- Передаём номер поставки в шаблон
    )


# --------------------------
# 4.1) Приём сканов (AJAX) в коробку
# --------------------------


from datetime import datetime

@app.route('/scan_box/<int:box_id>/submit', methods=['POST'])
def submit_scan(box_id):
    if 'who' not in session:
        return jsonify({'status': 'error', 'message': 'Не авторизован'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'No JSON data'}), 400

    code = data.get('code')
    if not code:
        return jsonify({'status': 'error', 'message': 'No code provided'}), 400

    delivery_id = session.get('delivery_id')
    who = session.get('who', 'UNKNOWN')

    conn = connect_to_db()
    if not conn:
        return jsonify({'status': 'error', 'message': 'DB connection failed'}), 500

    try:
        cursor = conn.cursor()

        # -----------------------------------------------------------
        # [A] Проверяем, не InnerBarcode ли это (т.е. содержит '-')
        #     Если да -> Переход на другую коробку
        # -----------------------------------------------------------
        if '-' in code:
            cursor.execute("""
                SELECT ID, ID_DeliveriesMP, NumCase
                FROM DITE_Deliveries_MPCase_v2
                WHERE InnerBarcode = ?
            """, (code,))
            row_case = cursor.fetchone()
            if row_case:
                new_box_id      = row_case[0]
                new_delivery_id = row_case[1]
                new_num_case    = row_case[2]

                # Переключаемся на новую поставку (если нужно):
                session['delivery_id'] = new_delivery_id

                # Отправляем клиенту JSON с "status=redirect"
                # Клиент на JS проверит: if (data.status==='redirect') { location.href=data.url }
                return jsonify({
                    'status': 'redirect',
                    'url': url_for('scan_box', box_id=new_box_id)
                }), 200
            else:
                # Не нашли InnerBarcode
                return jsonify({
                    'status': 'error',
                    'message': 'Не найден штрихкод коробки (InnerBarcode) в DITE_Deliveries_MPCase_v2!'
                }), 400

        # -----------------------------------------------------------
        # [B] Если нет дефиса, считаем это обычный код товара
        #     Далее - логика двойного сканирования
        # -----------------------------------------------------------

        # 1) Проверяем, что коробка существует
        cursor.execute("SELECT NumCase FROM DITE_Deliveries_MPCase_v2 WHERE ID = ?", (box_id,))
        row_case = cursor.fetchone()
        if not row_case:
            return jsonify({'status': 'error', 'message': 'Коробка не найдена!'}), 400
        num_case = row_case[0]

        # 2) Извлекаем ID_Codes из DITE_CM_GTIN_Codes_v2_UniqPrint (для двойного скана)
        cursor.execute("SELECT ID_Codes FROM DITE_CM_GTIN_Codes_v2_UniqPrint WHERE Codes = ?", (code,))
        row_idcodes = cursor.fetchone()
        if not row_idcodes:
            # Сбрасываем «первый скан», если был
            if 'first_scan_code' in session:
                session.pop('first_scan_code', None)
                session.pop('first_scan_id_codes', None)
                session.pop('first_scan_time', None)
            return jsonify({'status': 'error', 'message': 'QR-код не найден в базе'}), 400
        current_id_codes = row_idcodes[0]

        # 3) Проверяем, что товар действительно принадлежит данной поставке/коробке
        cursor.execute("""
            SELECT COUNT(*)
            FROM DITE_CM_GTIN_Codes_v2
            WHERE ID = ?
              AND ID_Documents = ?
              AND CasesNum = ?
        """, (current_id_codes, delivery_id, num_case))
        if cursor.fetchone()[0] == 0:
            if 'first_scan_code' in session:
                session.pop('first_scan_code', None)
                session.pop('first_scan_id_codes', None)
                session.pop('first_scan_time', None)
            return jsonify({
                'status': 'error',
                'message': 'Товар не соответствует поставке или коробке!'
            }), 400

        # 4) Получаем честный знак (Codes)
        cursor.execute("SELECT Codes FROM DITE_CM_GTIN_Codes_v2 WHERE ID = ?", (current_id_codes,))
        row_codes = cursor.fetchone()
        if not row_codes:
            if 'first_scan_code' in session:
                session.pop('first_scan_code', None)
                session.pop('first_scan_id_codes', None)
                session.pop('first_scan_time', None)
            return jsonify({
                'status': 'error',
                'message': 'Не найден честный знак в DITE_CM_GTIN_Codes_v2!'
            }), 400
        real_honest_sign = row_codes[0]

        # 5) Проверяем, не отсканирован ли уже
        cursor.execute("""
            SELECT ID_Case, NumCase, ID_DeliveriesMP
            FROM DITE_Deliveries_MPScans
            WHERE ID_DeliveriesMP = ? AND ID_Product = ?
        """, (delivery_id, real_honest_sign))
        already_scanned = cursor.fetchone()
        if already_scanned:
            if 'first_scan_code' in session:
                session.pop('first_scan_code', None)
                session.pop('first_scan_id_codes', None)
                session.pop('first_scan_time', None)
            return jsonify({'status': 'error', 'message': 'Товар уже отсканирован.'}), 400

        # 6) Логика двойного сканирования
        if 'first_scan_code' not in session:
            # Первый скан
            time_first_scan = datetime.now().strftime('%H:%M:%S')
            session['time_first_scan'] = time_first_scan
            session['first_scan_code'] = code
            session['first_scan_id_codes'] = current_id_codes

            return jsonify({
                'status': 'intermediate',
                'message': 'Скан 1/2 сохранен. Сканируйте второй QR-код.',
                'scanned_count': 0
            }), 200

        # === Второй скан ===
        # Проверяем, если код совпадает с первым - не сбрасываем
        if code == session.get('first_scan_code'):
            return jsonify({
                'status': 'error',
                'message': 'Этот QR-код уже отсканирован как первый. Сканируйте другой.'
            }), 400

        # Проверяем, что ID_Codes совпадает
        if current_id_codes != session.get('first_scan_id_codes'):
            session.pop('first_scan_code', None)
            session.pop('first_scan_id_codes', None)
            session.pop('time_first_scan', None)
            return jsonify({
                'status': 'error',
                'message': 'Несовпадение сканов – упаковка и товар не соответствуют друг другу.'
            }), 400

        # 7) Время первого и второго скана
        time_first_scan = session.get('time_first_scan')
        if not time_first_scan:
            return jsonify({
                'status': 'error',
                'message': 'Первый скан не найден в сессии. Начните заново.'
            }), 400
        time_second_scan = datetime.now().strftime('%H:%M:%S')

        # 8) Проверяем, не заполнена ли коробка
        cursor.execute("""
            SELECT COUNT(*)
            FROM DITE_Deliveries_MPScans
            WHERE ID_Case = ? AND ID_DeliveriesMP = ?
        """, (box_id, delivery_id))
        scanned_count_before = cursor.fetchone()[0]

        cursor.execute("""
            SELECT SUM(Counts)
            FROM DITE_Deliveries_MPArticulsToTPositionsCase_v2
            WHERE ID_DeliveriesMP = ? AND ID_Case = ?
        """, (delivery_id, box_id))
        total_required = cursor.fetchone()[0] or 0

        if scanned_count_before >= total_required:
            session.pop('first_scan_code', None)
            session.pop('first_scan_id_codes', None)
            session.pop('time_first_scan', None)
            return jsonify({
                'status': 'error',
                'message': 'Эта коробка уже заполнена!'
            }), 400

        # 9) Вставляем запись
        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d')
        time_str = now.strftime('%H:%M:%S')

        cursor.execute("""
            INSERT INTO DITE_Deliveries_MPScans
            (ID_Case, NumCase, ID_DeliveriesMP, Who,
             DateScan, TimeScan, ID_Product, Scan_Status,
             ID_Codes, TimeFirstScan, TimeSecondScan)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            box_id,
            num_case,
            delivery_id,
            who,
            date_str,
            time_str,
            real_honest_sign,
            'OK',
            current_id_codes,
            time_first_scan,
            time_second_scan
        ))

        # 10) Пересчитываем сканы
        cursor.execute("""
            SELECT COUNT(*)
            FROM DITE_Deliveries_MPScans
            WHERE ID_Case = ? AND ID_DeliveriesMP = ?
        """, (box_id, delivery_id))
        scanned_count_after = cursor.fetchone()[0]
        completed = (scanned_count_after >= total_required)
        scan_status = 'Готово ✅' if completed else 'Не готово ❌'

        if completed:
            cursor.execute("""
                UPDATE DITE_Deliveries_MPArticulsToTPositionsCase_v2
                SET WhoMarket  = ?,
                    DateMarket = ?,
                    TimeMarket = ?
                WHERE ID_Case = ?
                AND WhoMarket  IS NULL
                AND DateMarket IS NULL
                AND TimeMarket IS NULL
            """, (
                who,
                date_str,
                time_str,
                box_id
            ))





        # 11) Обновляем/вставляем в DITE_Deliveries_MPScans_Cases (если используете)
        cursor.execute("""
            SELECT COUNT(*)
            FROM DITE_Deliveries_MPScans_Cases
            WHERE ID_Case = ? AND ID_DeliveriesMP = ?
        """, (box_id, delivery_id))
        exists = cursor.fetchone()[0]

        if exists > 0:
            cursor.execute("""
                UPDATE DITE_Deliveries_MPScans_Cases
                SET NumCase = ?,
                    Counts = ?,
                    Counts_TSD = ?,
                    Who = ?,
                    DateScan = ?,
                    TimeScan = ?,
                    Scan_Status = ?
                WHERE ID_Case = ? AND ID_DeliveriesMP = ?
            """, (
                num_case,
                total_required,
                scanned_count_after,
                who,
                date_str,
                time_str,
                scan_status,
                box_id,
                delivery_id
            ))
        else:
            cursor.execute("""
                INSERT INTO DITE_Deliveries_MPScans_Cases
                (ID_Case, NumCase, ID_DeliveriesMP, Counts, Counts_TSD,
                 Who, DateScan, TimeScan, Scan_Status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                box_id,
                num_case,
                delivery_id,
                total_required,
                scanned_count_after,
                who,
                date_str,
                time_str,
                scan_status
            ))

        # 12) Формируем last_item для ответа
        cursor.execute("""
            SELECT
                cc.UniqCounts,
                dt.Sizes,
                dt.HeightsRus,
                dt.Articul,
                m.Models,
                c.Color
            FROM DITE_Deliveries_MPScans s
            JOIN DITE_CM_GTIN_Codes_v2 cc ON cc.Codes = s.ID_Product
            JOIN DITE_DeliveriesTasks dt ON dt.ID = cc.ID_Task
            JOIN DITE_Articuls a ON a.Articul = dt.Articul
            JOIN DITE_Articuls_Models m ON m.ID_Articuls = a.ID
            JOIN DITE_Articuls_Cloaths ac ON ac.ID_Articuls = a.ID
            JOIN DITE_Cloaths c ON c.ID = ac.ID_Cloath
            WHERE s.ID_Case = ?
              AND s.ID_DeliveriesMP = ?
              AND s.ID_Product = ?
        """, (box_id, delivery_id, real_honest_sign))
        row_item = cursor.fetchone()
        if row_item:
            size_height = ""
            if row_item[1] and row_item[2]:
                size_height = f"{row_item[1]}-{row_item[2]}"
            last_item = {
                'Uniq': row_item[0],
                'SizeHeight': size_height,
                'Articul': row_item[3],
                'Models': row_item[4],
                'Color': row_item[5],
            }
        else:
            last_item = None

        conn.commit()

        # Сбрасываем данные первого скана
        session.pop('first_scan_code', None)
        session.pop('first_scan_id_codes', None)
        session.pop('time_first_scan', None)

        return jsonify({
            'status': 'success',
            'scanned_count': scanned_count_after,
            'total_required': total_required,
            'completed': completed,
            'last_item': last_item
        }), 200

    except Exception as e:
        conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        conn.close()


@app.route('/boxes/search', methods=['POST'])
def boxes_search():
    if 'who' not in session:
        return redirect(url_for('login'))

    code = request.form.get('boxes_search', '').strip()
    if not code:
        # Если поле пустое, тоже просто вернёмся на /boxes
        return redirect(url_for('boxes'))

    conn = connect_to_db()
    if not conn:
        # Если нет подключения, тоже остаёмся
        return redirect(url_for('boxes'))

    try:
        cursor = conn.cursor()

        # Проверяем дефис (InnerBarcode)
        if '-' in code:
            cursor.execute("""
                SELECT ID, ID_DeliveriesMP
                FROM DITE_Deliveries_MPCase_v2
                WHERE InnerBarcode = ?
            """, (code,))
            row_case = cursor.fetchone()
            if row_case:
                new_box_id = row_case[0]
                new_del_id = row_case[1]
                session['delivery_id'] = new_del_id
                return redirect(url_for('scan_box', box_id=new_box_id))
            else:
                # Не нашли коробку => просто остаёмся
                return redirect(url_for('boxes'))
        else:
            # Иначе считаем «номер поставки»
            cursor.execute("""
                SELECT COUNT(*)
                FROM DITE_Deliveries_MP_v2
                WHERE ID = ?
            """, (code,))
            row = cursor.fetchone()
            if row[0] == 0:
                # Не нашли поставку => просто остаёмся
                return redirect(url_for('boxes'))

            # Нашли => переключаемся и переходим на /boxes
            session['delivery_id'] = code
            return redirect(url_for('boxes'))

    except Exception as e:
        # Если ошибка на уровне БД — тоже просто вернёмся
        return redirect(url_for('boxes'))
    finally:
        conn.close()













@app.route('/box_contents/<int:box_id>')
def box_contents(box_id):
    if 'who' not in session:
        return redirect(url_for('login'))

    delivery_id = session.get('delivery_id')
    if not delivery_id:
        return redirect(url_for('delivery'))

    conn = connect_to_db()
    if not conn:
        return "Ошибка подключения к БД", 500

    try:
        cursor = conn.cursor()

        # Узнаём NumCase (необязательно, но для заголовка)
        cursor.execute("SELECT NumCase FROM DITE_Deliveries_MPCase_v2 WHERE ID = ?", (box_id,))
        row_case = cursor.fetchone()
        num_case = row_case[0] if row_case else None

        # Запрос, который берёт ВСЕ товары, которые должны быть в этой коробке,
        # а также LEFT JOIN к DITE_Deliveries_MPScans (если товар отсканирован).
        query = """
        SELECT
        cc.Codes,
        cc.UniqCounts,
        dt.Sizes,
        dt.HeightsRus,
        dt.Articul,
        m.Models,
        c.Color,
        c.TypesCloaths,
        s.ID_Case AS ScannedCase
        FROM DITE_CM_GTIN_Codes_v2 cc
        JOIN DITE_DeliveriesTasks dt
        ON dt.ID = cc.ID_Task
        JOIN DITE_Articuls a
        ON a.Articul = dt.Articul
        JOIN DITE_Articuls_Models m
        ON m.ID_Articuls = a.ID
        JOIN DITE_Articuls_Cloaths ac
        ON ac.ID_Articuls = a.ID
        JOIN DITE_Cloaths c
        ON c.ID = ac.ID_Cloath
        LEFT JOIN DITE_Deliveries_MPScans s
        ON s.ID_Product = cc.Codes
        AND s.ID_DeliveriesMP = ?
        AND s.ID_Case = ?
        WHERE cc.ID_Documents = ?
        AND cc.CasesNum = ?
        ORDER BY
        CASE WHEN s.ID_Case IS NULL THEN 0 ELSE 1 END,
        cc.Codes
        """

        cursor.execute(query, (delivery_id, box_id, delivery_id, num_case))
        rows = cursor.fetchall()

        items = []
        for r in rows:
            codes       = r[0]  # cc.Codes
            uniq        = r[1]  # cc.UniqCounts
            sizes       = r[2]  # dt.Sizes
            heightsRus  = r[3]  # dt.HeightsRus
            articul     = r[4]  # dt.Articul
            models      = r[5]  # m.Models
            color       = r[6]  # c.Color
            types       = r[7]  # c.TypesCloaths
            scannedcase = r[8]  # s.ID_Case (NULL или box_id)

            size_height = ""
            if sizes and heightsRus:
                size_height = f"{sizes}-{heightsRus}"

            scanned = (scannedcase is not None)  # True, если товар отсканирован

            items.append({
                'Codes': codes,
                'Uniq': uniq,
                'SizeHeight': size_height,
                'Articul': articul,
                'Models': models,
                'Color': color,
                'Types': types,
                'Scanned': scanned
            })

        return render_template('box_contents.html',
            box_id=box_id,
            num_case=num_case,
            items=items
        )
    except Exception as e:
        conn.rollback()
        logger.exception("Ошибка при получении содержимого коробки:")
        return f"Ошибка: {e}", 500
    finally:
        conn.close()




# --------------------------
# 5) Завершение сканирования (кнопка "Завершить")
#    Обновляем только коробки, в которых поменялось Counts_TSD
# --------------------------
@app.route('/finish', methods=['POST'])
def finish_delivery():
    if 'who' not in session:
        return redirect(url_for('login'))

    # Удаляем из сессии информацию о текущей поставке и коробках
    session.pop('delivery_id', None)
    session.pop('boxes_info', None)

    # Возвращаемся на экран ввода номера поставки
    return redirect(url_for('delivery'))



# ---------------------------------------------------------------------
# Дополнительные (debug, scans)
# ---------------------------------------------------------------------
@app.route('/debug', methods=['POST'])
def debug_post():
    print("request.headers =", request.headers)
    print("request.data =", request.data)
    print("request.form =", request.form)
    print("request.json =", request.json)
    return "OK", 200

@app.route('/scans', methods=['GET'])
def get_scans():
    conn = connect_to_db()
    if not conn:
        return jsonify({'status': 'error', 'message': 'DB connection failed'}), 500

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                ID, ID_Case, NumCase, ID_DeliveriesMP, Who,
                DateScan, TimeScan, ID_Product, Scan_Status
            FROM DITE_Deliveries_MPScans
            ORDER BY ID DESC
        """)
        rows = cursor.fetchall()

        scans = []
        for row in rows:
            scans.append({
                'ID': row[0],
                'ID_Case': row[1],
                'NumCase': row[2],
                'ID_DeliveriesMP': row[3],
                'Who': row[4],
                'DateScan': str(row[5]),
                'TimeScan': str(row[6]),
                'ID_Product': row[7],
                'Scan_Status': row[8],
            })
        return jsonify({'status': 'success', 'data': scans}), 200
    except Exception as e:
        logger.exception("Ошибка при чтении записей из БД:")
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        conn.close()

@app.route('/admin_mode', methods=['POST'])
def admin_mode():
    data = request.get_json()
    if data.get('code') == 'DELETE':
        session['admin_mode'] = True
        return jsonify({'status': 'success'}), 200
    return jsonify({'status': 'error', 'message': 'Неверный админ код'}), 400


@app.route('/delete_box', methods=['GET', 'POST'])
def delete_box():
    if request.method == 'GET':
        return render_template('delete_box.html')

    if 'who' not in session:
        return jsonify({'status': 'error', 'message': 'Не авторизован'}), 403

    data = request.get_json()
    target_code = data.get('target_code')
    if not target_code:
        return jsonify({'status': 'error', 'message': 'Не указан штрихкод коробки'}), 400

    conn = connect_to_db()
    if not conn:
        return jsonify({'status': 'error', 'message': 'Ошибка подключения к БД'}), 500

    try:
        cursor = conn.cursor()
        # 1) Находим коробку по InnerBarcode
        cursor.execute("""
            SELECT ID, ID_DeliveriesMP, NumCase
            FROM DITE_Deliveries_MPCase_v2
            WHERE InnerBarcode = ?
        """, (target_code,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'status': 'error', 'message': 'Коробка не найдена'}), 400

        box_id, delivery_id, num_case = row

        # 2) Проверяем, кто отсканировал коробку
        cursor.execute("""
            SELECT WhoMarket
            FROM DITE_Deliveries_MPArticulsToTPositionsCase_v2
            WHERE ID_Case = ?
        """, (box_id,))
        row_market = cursor.fetchone()
        if row_market and row_market[0] is not None:
            # Если коробку сканировал кто-то, то разрешаем удаление только тому же пользователю
            if row_market[0] != session.get('who'):
                return jsonify({
                    'status': 'error',
                    'message': 'Вы не отсканировали эту коробку, удаление невозможно'
                }), 403

        # 3) Если проверка пройдена, удаляем данные, связанные с этой коробкой:
        cursor.execute("""
            DELETE FROM DITE_Deliveries_MPScans
            WHERE ID_Case = ? AND ID_DeliveriesMP = ?
        """, (box_id, delivery_id))

        cursor.execute("""
            DELETE FROM DITE_Deliveries_MPScans_Cases
            WHERE ID_Case = ? AND ID_DeliveriesMP = ?
        """, (box_id, delivery_id))

        # 4) Обнуляем данные в DITE_Deliveries_MPArticulsToTPositionsCase_v2 (только если удаляет тот, кто отсканировал)
        cursor.execute("""
            UPDATE DITE_Deliveries_MPArticulsToTPositionsCase_v2
            SET WhoMarket  = NULL,
                DateMarket = NULL,
                TimeMarket = NULL
            WHERE ID_Case = ?
            AND WhoMarket = ?
        """, (box_id, session.get('who')))


        conn.commit()

        return jsonify({
            'status': 'success',
            'message': 'Сканы коробки удалены, данные очищены.'
        }), 200

    except Exception as e:
        conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        conn.close()




@app.route('/delete_scan', methods=['GET', 'POST'])
def delete_scan():
    if request.method == 'GET':
        return render_template('delete_scan.html')

    if 'who' not in session:
        return jsonify({'status': 'error', 'message': 'Не авторизован'}), 403

    data = request.get_json()
    target_code = data.get('target_code')
    if not target_code:
        return jsonify({'status': 'error', 'message': 'Не указан код для удаления'}), 400

    conn = connect_to_db()
    if not conn:
        return jsonify({'status': 'error', 'message': 'Ошибка подключения к БД'}), 500

    try:
        cursor = conn.cursor()
        # 1) Ищем ID_Codes в DITE_CM_GTIN_Codes_v2_UniqPrint
        cursor.execute("""
            SELECT ID_Codes
            FROM DITE_CM_GTIN_Codes_v2_UniqPrint
            WHERE Codes = ?
        """, (target_code,))
        row_idcodes = cursor.fetchone()
        if not row_idcodes:
            return jsonify({
                'status': 'error',
                'message': 'QR-код не найден в DITE_CM_GTIN_Codes_v2_UniqPrint!'
            }), 400

        id_codes = row_idcodes[0]

        # 2) Находим запись в DITE_Deliveries_MPScans по ID_Codes
        cursor.execute("""
            SELECT ID, ID_Case, ID_DeliveriesMP
            FROM DITE_Deliveries_MPScans
            WHERE ID_Codes = ?
        """, (id_codes,))
        row_scan = cursor.fetchone()
        if not row_scan:
            return jsonify({
                'status': 'error',
                'message': 'Запись с таким ID_Codes не найдена в DITE_Deliveries_MPScans!'
            }), 400

        scan_id, box_id, delivery_id = row_scan

        # 3) Удаляем строку
        cursor.execute("""
            DELETE FROM DITE_Deliveries_MPScans
            WHERE ID = ?
        """, (scan_id,))

        # 4) Пересчитываем количество сканов
        cursor.execute("""
            SELECT COUNT(*)
            FROM DITE_Deliveries_MPScans
            WHERE ID_Case = ? AND ID_DeliveriesMP = ?
        """, (box_id, delivery_id))
        scanned_count_after = cursor.fetchone()[0]

        # 5) Узнаём, сколько всего нужно в коробке
        cursor.execute("""
            SELECT SUM(Counts)
            FROM DITE_Deliveries_MPArticulsToTPositionsCase_v2
            WHERE ID_DeliveriesMP = ? AND ID_Case = ?
        """, (delivery_id, box_id))
        total_required = cursor.fetchone()[0] or 0

        completed = (scanned_count_after >= total_required)
        scan_status = 'Готово ✅' if completed else 'Не готово ❌'

        # 6) Обновляем DITE_Deliveries_MPScans_Cases
        cursor.execute("""
            SELECT COUNT(*)
            FROM DITE_Deliveries_MPScans_Cases
            WHERE ID_Case = ? AND ID_DeliveriesMP = ?
        """, (box_id, delivery_id))
        exists = cursor.fetchone()[0]

        if exists > 0:
            cursor.execute("""
                UPDATE DITE_Deliveries_MPScans_Cases
                SET Counts_TSD = ?,
                    Scan_Status = ?
                WHERE ID_Case = ? AND ID_DeliveriesMP = ?
            """, (scanned_count_after, scan_status, box_id, delivery_id))
        else:
            cursor.execute("""
                INSERT INTO DITE_Deliveries_MPScans_Cases
                (ID_Case, ID_DeliveriesMP, Counts_TSD, Scan_Status)
                VALUES (?, ?, ?, ?)
            """, (box_id, delivery_id, scanned_count_after, scan_status))

        conn.commit()

        # === КЭШИРОВАНИЕ УДАЛЕНИЯ ===
        who = session.get('who', 'UNKNOWN')
        # Формируем текст
        result_str = (f"Удалил скан (ID={scan_id}), "
                      f"QR={target_code}, ID_Codes={id_codes}, "
                      f"Коробка={box_id}, Поставка={delivery_id}.")

        # Вызываем функцию кэширования
        cache_bot_history(who, result_str)

        return jsonify({'status': 'success', 'message': 'Скан удалён, данные обновлены.'}), 200

    except Exception as e:
        conn.rollback()



def cache_bot_history(who: str, result: str):
    connection = connect_to_db()
    if not connection:
        logger.error("Не удалось подключиться к базе данных для кэширования истории.")
        return
    try:
        cursor = connection.cursor()
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")
        query = """
            INSERT INTO DITE_BOT_PRIB_HISTORY (WHO, DATE, TIME, RESULT)
            VALUES (?, ?, ?, ?)
        """
        cursor.execute(query, (who, date_str, time_str, result))
        connection.commit()
        logger.info("Кэширование истории выполнено успешно.")
    except Exception as e:
        logger.error(f"Ошибка кэширования истории: {e}")
        connection.rollback()
    finally:
        connection.close()

@app.route('/carry', methods=['GET'])
def carry():
    if 'who' not in session:
        return redirect(url_for('login'))
    return render_template('carry.html')


@app.route('/carry/info', methods=['POST'])
def carry_info():
    """
    Принимает QR‑код товара (product_code) и возвращает информацию о товаре из DITE_CM_GTIN_Codes_v2:
      - honest_sign: фактический код (честный знак),
      - uniq_counts: уникальное количество (UniqCounts),
      - ID_task: складская задача,
      - ID_Documents: номер поставки,
      - CasesNum: физический номер коробки.
    Сохранённые данные помещаются в session['carry_product_info'] для последующей проверки.
    """
    if 'who' not in session:
        return jsonify({'status': 'error', 'message': 'Не авторизован'}), 403

    data = request.get_json()
    if not data or 'product_code' not in data:
        return jsonify({'status': 'error', 'message': 'Нет данных о товаре'}), 400

    product_code = data.get('product_code')
    conn = connect_to_db()
    if not conn:
        return jsonify({'status': 'error', 'message': 'Ошибка подключения к БД'}), 500

    try:
        cursor = conn.cursor()
        # Шаг 1: Получаем ID_codes из UniqPrint
        cursor.execute("""
            SELECT ID_codes
            FROM DITE_CM_GTIN_Codes_v2_UniqPrint
            WHERE Codes = ?
        """, (product_code,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'status': 'error', 'message': 'QR‑код не найден'}), 400
        id_codes = row[0]

        # Шаг 2: Получаем данные о товаре из DITE_CM_GTIN_Codes_v2
        cursor.execute("""
            SELECT Codes, UniqCounts, ID_task, ID_Documents, CasesNum
            FROM DITE_CM_GTIN_Codes_v2
            WHERE ID = ?
        """, (id_codes,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'status': 'error', 'message': 'Данные о товаре не найдены'}), 400

        honest_sign, uniq_counts, id_task, id_documents, cases_num = row

        result = {
            'honest_sign': honest_sign,
            'uniq_counts': uniq_counts,
            'ID_task': id_task,
            'ID_Documents': id_documents,
            'CasesNum': cases_num
        }
        # Сохраняем данные о товаре в сессии для последующей проверки целевой коробки
        session['carry_product_info'] = result




        return jsonify({'status': 'success', 'data': result}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        conn.close()


@app.route('/carry/target-info', methods=['POST'])
def carry_target_info():
    """
    Принимает штрихкод целевой коробки (target_code) и ищет запись в DITE_Deliveries_MPCase_v2 по полю InnerBarcode.
    Возвращает:
      - ID (целевой ID коробки),
      - ID_DeliveriesMP (номер поставки),
      - NumCase (физический номер коробки).
    Дополнительно проверяет, что номер поставки целевой коробки совпадает с номером поставки товара,
    сохранённым в session['carry_product_info'] (поле ID_Documents).
    Если поставки не совпадают, сразу возвращается ошибка.
    """
    if 'who' not in session:
        return jsonify({'status': 'error', 'message': 'Не авторизован'}), 403
    if 'carry_product_info' not in session:
        return jsonify({'status': 'error', 'message': 'Информация о товаре отсутствует'}), 400

    data = request.get_json()
    if not data or 'target_code' not in data:
        return jsonify({'status': 'error', 'message': 'Нет данных о коробке'}), 400

    target_code = data.get('target_code')
    conn = connect_to_db()
    if not conn:
        return jsonify({'status': 'error', 'message': 'Ошибка подключения к БД'}), 500

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ID, ID_DeliveriesMP, NumCase
            FROM DITE_Deliveries_MPCase_v2
            WHERE InnerBarcode = ?
        """, (target_code,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'status': 'error', 'message': 'Коробка не найдена'}), 400

        target_info = {
            'ID': row[0],
            'ID_DeliveriesMP': row[1],
            'NumCase': row[2]
        }

        # Проверяем, что поставка товара совпадает с поставкой целевой коробки
        product_info = session.get('carry_product_info')
        if not product_info:
            return jsonify({'status': 'error', 'message': 'Информация о товаре отсутствует'}), 400

        if product_info.get('ID_Documents') != target_info['ID_DeliveriesMP']:
            return jsonify({'status': 'error', 'message': 'Целевая коробка принадлежит другой поставке'}), 400;

        return jsonify({'status': 'success', 'data': target_info}), 200;

    except Exception as e:
        conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500;
    finally:
        conn.close();


@app.route('/carry/transfer', methods=['POST'])
def carry_transfer():
    """
    Выполняет перенос товара.
    Ожидает:
      - product_code: оригинальный QR‑код товара (как передан клиентом),
      - target_box_id: ID целевой коробки (из DITE_Deliveries_MPCase_v2).
    Хранимая процедура pr2_МП_ПереносТовараМеждуПополнением_ТекущееПополнение_v2
    внутри себя извлекает данные по QR‑коду, определяет исходную коробку и выполняет перенос,
    обновляя местоположение товара.
    """
    if 'who' not in session:
        return jsonify({'status': 'error', 'message': 'Не авторизован'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'Нет данных'}), 400

    product_code = data.get('product_code')
    target_box_id = data.get('target_box_id')
    who = session.get('who')

    if not all([product_code, target_box_id]):
        return jsonify({'status': 'error', 'message': 'Не все параметры переданы'}), 400

    conn = connect_to_db()
    if not conn:
        return jsonify({'status': 'error', 'message': 'Ошибка подключения к БД'}), 500

    try:
        cursor = conn.cursor();
        cursor.execute("""
            EXEC [u1603085_Maxim].[pr2_МП_ПереносТовараМеждуПополнением_ТекущееПополнение_v2]
                @product_code = ?,
                @target_box_id = ?,
                @who = ?
        """, (product_code, target_box_id, who))
        conn.commit();
        return jsonify({'status': 'success', 'message': 'Товар успешно перенесён'}), 200;
    except Exception as e:
        conn.rollback();
        return jsonify({'status': 'error', 'message': str(e)}), 500;
    finally:
        conn.close();


@app.route('/queues', methods=['GET'])
def queues():
    if 'who' not in session:
        return redirect(url_for('login'))
    return render_template('queues.html')

@app.route('/queue/<string:turn>', methods=['GET'])

def queue_turn(turn):
    who = session.get('who')
    # prev_id = request.args.get('prev_id', type=int)
    if 'who' not in session:
        return redirect(url_for('login'))
    
    conn = connect_to_db()
    if not conn:
        return "Ошибка подключения к БД", 500

    try:
        cursor = conn.cursor()

        # if prev_id:
        #     cursor.execute("""
        #         UPDATE DITE_DeliveriesOrders
        #         SET WhoReserved  = NULL,
        #             DateReserved = NULL,
        #             TimeReserved = NULL
        #         WHERE ID = ? AND WhoReserved = ?
        #     """, (prev_id, session['who']))
        #     conn.commit()

        # # -- A. Вызываем вашу процедуру мониторинга очереди
        # # -- A. Вызываем вашу процедуру мониторинга очереди
        # # теперь обязательно передаём и @Who
        cursor.execute(
            "EXEC [u1603085_Maxim].[pr2_Мониторинг_Очереди_Copy] @Turn = ?, @Who = ?",
            (turn, who)
        )

        # Пропускаем все непро-SELECT наборы, пока не найдём первый SELECT
        while cursor.description is None:
            if not cursor.nextset():
                break

        # Теперь либо description != None, либо наборов больше нет
        try:
            row = cursor.fetchone()
        except pyodbc.ProgrammingError:
            row = None

        if not row:
            flash(f"В очереди «{turn}» больше нет заказов.", "info")
            return redirect(url_for('queues'))

        columns = [col[0] for col in cursor.description]
        order_data = dict(zip(columns, row))
        logger.info("ORDER DATA KEYS: %s", order_data.keys())

        cursor.execute("""
            SELECT COUNT(*)
            FROM DITE_DeliveriesTasks
            WHERE ID_Orders   = ?
            AND LTRIM(RTRIM(ISNULL(Status,''))) = ''
            AND WhoConfrim  IS NULL
            AND DateConfrim IS NULL
            AND TimeConfrim IS NULL
        """, (order_data['ID'],))
        order_data['remaining_tasks'] = cursor.fetchone()[0]

        order_id = order_data.get('ID')
        if order_id:
            cursor.execute("""
                UPDATE DITE_DeliveriesOrders
                SET
                WhoReserved   = ?,
                DateReserved  = ?,
                TimeReserved  = ?
                WHERE ID = ?
                AND (WhoReserved IS NULL OR WhoReserved = '')
            """, (
                session['who'],
                datetime.now().strftime('%Y-%m-%d'),
                datetime.now().strftime('%H:%M:%S'),
                order_id
            ))
            conn.commit()
            order_data['WhoReserved']  = session['who']
            order_data['DateReserved'] = datetime.now().strftime('%Y-%m-%d')
            order_data['TimeReserved'] = datetime.now().strftime('%H:%M:%S')

        # -- B. Извлекаем Outputs, Inputs из таблицы DITE_Deliveries (если есть ID_Deliveries)
        if order_data.get('ID_Deliveries'):
            cursor.execute("""
                SELECT Outputs, Inputs
                FROM DITE_Deliveries
                WHERE ID = ?
            """, (order_data['ID_Deliveries'],))
            row_del = cursor.fetchone()
            if row_del:
                order_data['Outputs'] = row_del[0]
                order_data['Inputs']  = row_del[1]

        # -- C. Если в Inputs есть 'LM' или 'WB', получаем номер поставки
        order_data['NumPostavki'] = None
        inputs_value = order_data.get('Inputs', '')

# Новый блок: правильный выбор NumPostavki
        if ('LM' in inputs_value or 'WB' in inputs_value):
            # 1) ищем первую незавершённую складскую задачу для этого заказа+поставки
            cursor.execute("""
                SELECT TOP 1 ID
                FROM DITE_DeliveriesTasks
                WHERE ID_Orders     = ?
                AND ID_Deliveries = ?
                AND LTRIM(RTRIM(ISNULL(Status,''))) = ''
                AND WhoConfrim   IS NULL
                AND DateConfrim  IS NULL
                AND TimeConfrim  IS NULL
                ORDER BY ID
            """, (order_id, order_data['ID_Deliveries']))
            row_task = cursor.fetchone()

            if row_task:
                id_task = row_task[0]
                # 2) подтягиваем ID_DeliveriesMP по этому ID_Task
                cursor.execute("""
                    SELECT TOP 1 ID_DeliveriesMP
                    FROM DITE_Deliveries_MPArticulsToPositions_v2
                    WHERE ID_Task = ?
                """, (id_task,))
                row_mp = cursor.fetchone()
                if row_mp and row_mp[0] is not None:
                    order_data['NumPostavki'] = row_mp[0]


        # Передаём все данные в шаблон
        return render_template('order_details.html', order=order_data, queue=turn)

    except Exception as e:
        return str(e), 500
    finally:
        conn.close()




@app.route('/release_and_queues')
def release_and_queues():
    if 'who' not in session:
        return redirect(url_for('login'))
    prev_id = request.args.get('prev_id', type=int)
    if prev_id:
        conn = connect_to_db()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE DITE_DeliveriesOrders
            SET WhoReserved  = NULL,
                DateReserved = NULL,
                TimeReserved = NULL
            WHERE ID = ? AND WhoReserved = ?
        """, (prev_id, session['who']))
        conn.commit()
        conn.close()
    return redirect(url_for('queues'))

from flask import abort, jsonify, redirect, url_for, session, request
from datetime import datetime

@app.route('/print_document', methods=['GET'])
def print_document():
    # 0) Проверка авторизации
    if 'who' not in session:
        return redirect(url_for('login'))

    # 1) Считываем и валидируем GET-параметры
    try:
        id_deliveries = int(request.args['id_deliveries'])
        id_orders     = int(request.args['id_orders'])
    except (KeyError, ValueError):
        abort(400, "Неверные параметры id_deliveries или id_orders")

    queue = request.args.get('queue', '')

    # 2) Метаданные создания
    who_create  = session['who']
    now         = datetime.now()
    date_create = now.date().isoformat()        # 'YYYY-MM-DD'
    time_create = now.time().strftime('%H:%M:%S')

    # 3) Подключаемся к БД
    try:
        with connect_to_db() as conn:
            cursor = conn.cursor()

            # 4) Получаем все невыполненные задачи этого deliveries+orders
            cursor.execute("""
                SELECT t.ID        AS task_id,
                       t.Tho       AS tho,
                       dp.ID_Division AS store
                FROM DITE_DeliveriesTasks t
                LEFT JOIN DITE_DivisionsPlaces dp
                  ON dp.Place = t.Tho
                WHERE t.ID_Deliveries = ?
                  AND t.ID_Orders     = ?
                  AND t.WhoConfrim   IS NULL
                  AND t.DateConfrim  IS NULL
                  AND t.TimeConfrim  IS NULL
            """, (id_deliveries, id_orders))

            rows = cursor.fetchall()
            if not rows:
                abort(404, "Нет задач для печати")

            # 5) Подготовим payload для bulk-insert
            to_insert = []
            for task_id, tho, store in rows:
                # Логика формирования Group
                if   queue == "Перемещение": group = "Перемещение"
                elif queue == "Приёмка":     group = "Документ"
                elif queue == "На МП":     group = "МП"
                elif queue == "На магазин":
                    group = "МП" if ("LM" in tho or "WB" in tho) else "Магазин"
                else:
                    group = ""

                to_insert.append((
                    task_id,
                    who_create,
                    date_create,
                    time_create,
                    store,
                    group
                ))

            # 6) Вставляем все разом
            cursor.executemany("""
                INSERT INTO DITE_Queue_TaskPrint
                  (id_task, WhoCreate, DateCreate, TimeCreate, Store, [Group])
                VALUES (?, ?, ?, ?, ?, ?)
            """, to_insert)

            conn.commit()

            # 7) Возвращаем JSON с числом вставленных записей
            return jsonify({
                "status":   "ok",
                "inserted": len(to_insert)
            })

    except Exception as e:
        # На случай ошибки — откат и 500
        conn.rollback()
        logger.exception("Ошибка формирования печатного документа")
        abort(500, str(e))


from flask import Flask, request, jsonify, render_template, session, redirect, url_for


@app.route('/order_details')
def order_details():
    # 0) Авторизация
    if 'who' not in session:
        return redirect(url_for('login'))

    # 1) Параметры из URL
    order_id      = request.args.get('order_id',    type=int)
    id_deliveries = request.args.get('id_deliveries', type=int)
    queue         = request.args.get('queue',       type=str, default='')


    if not order_id or not id_deliveries:
        return "Не указан заказ или документ", 400

    conn   = connect_to_db()
    cursor = conn.cursor()
    try:
        # 2) Берём данные о самом заказе
        cursor.execute("""
            SELECT
            ID,
            ID_Deliveries,
            CountTask      AS total_tasks,
            Weights,
            [Values]       AS order_values,
            Status,
            WhoReserved,
            DateReserved,
            TimeReserved
            FROM DITE_DeliveriesOrders
            WHERE ID = ?
        """, (order_id,))
        row = cursor.fetchone()
        if not row:
            flash("Документ не найден", "error")
            return redirect(url_for('queues'))

        cols = [c[0] for c in cursor.description]
        order = dict(zip(cols, row))

        cursor.execute("""
        SELECT Outputs, Inputs
          FROM DITE_Deliveries
         WHERE ID = ?
        """, (id_deliveries,))
        row_del = cursor.fetchone()
        if row_del:
            order['Outputs'] = row_del[0]
            order['Inputs']  = row_del[1]


        # 3) Считаем оставшиеся таски
        cursor.execute("""
            SELECT COUNT(*) 
              FROM DITE_DeliveriesTasks
             WHERE ID_Orders     = ?
               AND ID_Deliveries = ?
               AND (Status     IS NULL OR Status = '')
               AND WhoConfrim   IS NULL
               AND DateConfrim  IS NULL
               AND TimeConfrim  IS NULL
        """, (order_id, id_deliveries))
        order['remaining_tasks'] = cursor.fetchone()[0] or 0

    except Exception as e:
        logger.exception("order_details: ошибка")
        return f"Ошибка: {e}", 500
    finally:
        conn.close()

    # 4) Рендерим шаблон, передаём туда order и queue
    return render_template('order_details.html',
                           order=order,
                           queue=queue)




@app.route('/transfer', methods=['GET', 'POST'])
def transfer():
    queue = request.args.get('queue')
    mode  = request.args.get('mode')
    who = session.get('who')
    if not who:
        return "Не авторизован", 401

    turn = 'Перемещение'
    skip_id = request.args.get('skip')

    conn = connect_to_db()
    if not conn:
        return "Ошибка подключения к базе данных", 500

    try:
        cursor = conn.cursor()
        session['scanned_count'] = 0
        cursor.execute(
            "EXEC [u1603085_Maxim].[pr2_Мониторинг_Очереди_Copy] @Turn=?, @Who=?",
            (turn, who)
        )
        # пропускаем все непро-SELECT-наборы
        while cursor.description is None:
            if not cursor.nextset():
                break
        try:
            row = cursor.fetchone()
        except pyodbc.ProgrammingError:
            row = None
        if not row:
            flash("✅ Все складские задачи по этому заказу выполнены.", "success")
            # берём последние сохранённые из сессии
            prev_order_id     = session.get('current_order_id')
            prev_delivery_id  = session.get('current_delivery_id')
            return redirect(url_for('order_details',
                                    order_id=prev_order_id,
                                    id_deliveries=prev_delivery_id,
                                    queue=queue))

        # есть новая задача — сохраняем её в сессионные переменные
        id_orders     = row[0]
        id_deliveries = row[1]
        session['current_order_id']    = id_orders
        session['current_delivery_id'] = id_deliveries

        cursor.execute("""
            SELECT ID, Types, Froms, Tho, Articul, HS, Sizes, Heights, HeightsRus, Counts
            FROM DITE_DeliveriesTasks
            WHERE ID_Deliveries = ? AND ID_Orders = ?
              AND ISNULL(Status, '') = ' '
              AND ISNULL(WhoConfrim, '') = ''
              AND ISNULL(DateConfrim, '') = ''
              AND ISNULL(TimeConfrim, '') = ''
        """, (id_deliveries, id_orders))
        rows = cursor.fetchall()
        if not rows:
            return "Все задачи уже выполнены", 200


        cursor.execute("""
            SELECT COUNT(*)
            FROM DITE_DeliveriesTasks
            WHERE ID_Deliveries = ? AND ID_Orders = ?
            AND LTRIM(RTRIM(ISNULL(Status,'')))      = ' '
            AND WhoConfrim   IS NULL
            AND DateConfrim  IS NULL
            AND TimeConfrim  IS NULL
        """, (id_deliveries, id_orders))
        remaining = cursor.fetchone()[0] or 0

        tasks = []
        for row in rows:
            task = {
                'task_number': row[0],
                'types': row[1],
                'from_cell': row[2],
                'target_cell': row[3],
                'articul': row[4],
                'hs': row[5],
                'sizes': row[6],
                'heights': row[7],
                'heightsrus': row[8],
                'counts': row[9],
                'id_orders': id_orders,
                'id_deliveries': id_deliveries,
            }
            tasks.append(task)

        # === СОРТИРОВКА ===
        if mode == 'articul':
            ordered = sorted(tasks, key=lambda t: str(t['articul']))
        else:
            # 1) Вызываем процедуру для получения уже упорядоченных строк
            cursor.execute("""
                EXEC [u1603085_Maxim].[pr2_ОптимизироватьОчередьПеремещений]
                    @id_orders = ?
            """, (id_orders,))
            rows = cursor.fetchall()

            # 2) Достаём имена колонок из cursor.description
            cols = [col[0] for col in cursor.description]

            # 3) Собираем список словарей — теперь ключи совпадают с алиасами из процедуры
            ordered = [dict(zip(cols, row)) for row in rows]

        active_ids = {t['task_number'] for t in tasks}
        ordered = [t for t in ordered if t['task_number'] in active_ids]
        
        qkey = 'transfer_queue'

        # 1) Инициализируем или пересоздаём очередь, если она появилась впервые
        if qkey not in session or len(session[qkey]) != len(ordered):
            session[qkey] = [t['task_number'] for t in ordered]
        transfer_queue = session[qkey]

        # 2) Обработка skip (если передали skip, переносим его ID в конец очереди)
        skip_id = request.args.get('skip', type=int)
        if skip_id and skip_id in transfer_queue:
            transfer_queue.remove(skip_id)
            transfer_queue.append(skip_id)
            session[qkey] = transfer_queue

        # 3) Определяем текущую задачу
        current_id = transfer_queue[0]
        t = next(x for x in ordered if x['task_number'] == current_id)
        task = t.copy()

        # 4) Считаем, сколько ещё осталось
# 4) Считаем, сколько ещё осталось именно у этого заказа
        remaining = get_remaining_tasks_count(
            task['id_orders'],
            task['id_deliveries']
        )
        task['remaining_tasks'] = remaining

        # Единожды дополняем наш текущий task данными артикулов/цвета
        cursor.execute("SELECT Gender, ID FROM DITE_Articuls WHERE Articul = ?", (t['articul'],))
        row = cursor.fetchone()
        gender, id_articul = (row[0], row[1]) if row else ("", None)
        model, color = "", ""
        if id_articul:
            cursor.execute("SELECT Models, ID FROM DITE_Articuls_Models WHERE ID_Articuls = ?", (id_articul,))
            row = cursor.fetchone()
            if row:
                model, id_model = row
                cursor.execute("SELECT Color FROM DITE_Cloaths WHERE ID = ?", (id_model,))
                c = cursor.fetchone()
                color = c[0] if c else ""
        task.update({'gender': gender, 'model': model, 'color': color})

        # Возвращаем в шаблон уже готовый task
        return render_template("transfer.html",
                               task=task,
                               queue=queue,
                               )


    except Exception as e:
        conn.rollback()
        return f"Ошибка: {e}", 500
    finally:
        conn.close()


# внизу файла app.py, после import-ов и перед @app.route('/queues') или рядом с ними

@app.route('/transfer/validate_source', methods=['POST'])
def validate_source():
    data = request.get_json() or {}
    cell = data.get('cell_code')
    task_id = data.get('task_id')
    if not cell or not task_id:
        return jsonify({'status':'error','message':'Нет данных для проверки'}), 400

    conn = connect_to_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT Froms FROM DITE_DeliveriesTasks WHERE ID = ?",
            (task_id,)
        )
        row = cursor.fetchone()
        if not row or row[0] != cell:
            return jsonify({'status':'error','message':'Неверная ячейка «Откуда»'}), 400
        return jsonify({'status':'success'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'status':'error','message':str(e)}), 500
    finally:
        conn.close()


@app.route('/transfer/validate_target', methods=['POST'])
def validate_target():
    data = request.get_json() or {}
    cell = data.get('cell_code')
    task_id = data.get('task_id')
    if not cell or not task_id:
        return jsonify({'status':'error','message':'Нет данных для проверки'}), 400

    conn = connect_to_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT Tho FROM DITE_DeliveriesTasks WHERE ID = ?",
            (task_id,)
        )
        row = cursor.fetchone()
        if not row or row[0] != cell:
            return jsonify({'status':'error','message':'Неверная ячейка «Куда»'}), 400
        return jsonify({'status':'success'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'status':'error','message':str(e)}), 500
    finally:
        conn.close()

@app.route('/transfer/scanned_count', methods=['GET'])
def transfer_scanned_count():
    """
    Возвращает JSON с текущим значением session['scanned_count'].
    """
    return jsonify({'scanned_count': session.get('scanned_count', 0)}), 200

@app.route('/transfer/scan_item', methods=['POST'])
def transfer_scan_item():
    """
    Принимает JSON с полями:
      - code: QR-код товара (строка)
      - task_id: ID складской задачи (целое число)
    Логика:
      1. По QrCode из DITE_Articuls_LabelsPrint извлекаем Articul и HS.
      2. Сверяем в DITE_DeliveriesTasks по task_id, Articul и HS.
      3. Если совпало, инкрементируем session['scanned_count'] и возвращаем новое значение.
    """
    # 1) Проверяем авторизацию
    if 'who' not in session:
        return jsonify({'status': 'error', 'message': 'Не авторизован'}), 403

    data = request.get_json() or {}
    code    = data.get('code')
    task_id = data.get('task_id')
    if not code or not task_id:
        return jsonify({'status': 'error', 'message': 'Нет данных для сканирования'}), 400

    # 2) Подключаемся к БД
    conn = connect_to_db()
    if not conn:
        return jsonify({'status': 'error', 'message': 'Ошибка подключения к БД'}), 500

    try:
        cursor = conn.cursor()

        # 3) Получаем Articul и HS по QrCode
        cursor.execute("""
            SELECT Articul, HS
            FROM DITE_Articuls_LabelsPrint
            WHERE QrCode = ?
        """, (code,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'status': 'error', 'message': 'QR-код не найден'}), 400
        articul, hs = row

        # 4) Проверяем соответствие в DITE_DeliveriesTasks
        cursor.execute("""
            SELECT COUNT(*)
            FROM DITE_DeliveriesTasks
            WHERE ID = ?
              AND Articul = ?
              AND HS = ?
        """, (task_id, articul, hs))
        if cursor.fetchone()[0] == 0:
            return jsonify({'status': 'error', 'message': 'Неверный товар для этой задачи'}), 400

        # 5) Инкрементируем счётчик в сессии
        from datetime import datetime

        # 5) Добавляем в список отсканов
        now = datetime.now()

        # Вычисляем секунды с начала дня для целочисленного TimeFact
        # seconds_since_midnight = now.hour * 3600 + now.minute * 60 + now.second

        # Формируем запись скана
        item = {
            'qrcode': code,                          # сам отсканированный QR-код
            'date_scan': now.strftime('%Y-%m-%d'),    # дата в формате YYYY-MM-DD
            'time_scan': now.strftime('%H:%M:%S'),    # время в формате HH:MM:SS
            'time_fact': now.hour*3600 + now.minute*60 + now.second       # целое число секунд с начала дня
        }
        scanned_items = session.get('scanned_items', [])
        scanned_items.append(item)
        session['scanned_items'] = scanned_items

        # 6) Инкрементируем счётчик
        scanned = session.get('scanned_count', 0) + 1
        session['scanned_count'] = scanned
        return jsonify({'status':'success','scanned_count':scanned}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

    finally:
        conn.close()

@app.route('/transfer/update_task', methods=['POST'])
def update_transfer_task():
    if 'who' not in session:
        return jsonify({'status': 'error', 'message': 'Не авторизован'}), 403

    data = request.get_json()
    id_task = data.get('id_task')
    counts = data.get('counts')

    if not id_task or counts is None:
        return jsonify({'status': 'error', 'message': 'Неверные данные'}), 400

    who = session['who']
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    time_str = now.strftime('%H:%M:%S')

    conn = connect_to_db()
    if not conn:
        return jsonify({'status': 'error', 'message': 'Ошибка подключения'}), 500

    try:
        cursor = conn.cursor()

        # Получаем whoIdUpdate
        cursor.execute("""
            SELECT ID FROM DITE_Logins WHERE Surname_N_LN = ?
        """, (who,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'status': 'error', 'message': 'Пользователь не найден'}), 404

        who_id = row[0]

        # Вызываем процедуру
        cursor.execute("""
            EXEC [u1603085_Maxim].[pr2_ServiceBroker_СкладскаяЗадача_Очередь_ОбновитьЗадачу]
            @idTask=?, @whoUpdate=?, @whoIdUpdate=?, @counts=?, @dateUpdate=?, @timeUpdate=?
        """, (id_task, who, who_id, counts, date_str, time_str))


        # Получаем ID_Orders и ID_Deliveries
        cursor.execute(
            "SELECT ID_Orders, ID_Deliveries FROM DITE_DeliveriesTasks WHERE ID = ?",
            (id_task,)
        )
        id_orders, id_deliveries = cursor.fetchone()

        # Вставляем все элементы из session['scanned_items']
        for itm in session.get('scanned_items', []):
            cursor.execute("""
                INSERT INTO DITE_DeliveriesTasksScans
                (QrCode, DateScan, TimeScan, TimeFact, ID_Task, ID_Orders, ID_Deliveries)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                itm['qrcode'],
                itm['date_scan'],
                itm['time_scan'],
                itm['time_fact'],
                id_task,
                id_orders,
                id_deliveries
            ))

        # Очищаем буфер
        session.pop('scanned_items', None)
        session.pop('scanned_count', None)



        conn.commit()

        

        # Ждем 1 секунду и проверяем статус
        import time
        time.sleep(1)

        cursor.execute("""
            SELECT Status
            FROM DITE_DeliveriesHistory_Tasks
            WHERE ID_Task = ? AND ID_Login = ? AND DateCreate = ? AND TimeCreate = ?
        """, (id_task, who_id, date_str, time_str))

        row = cursor.fetchone()
        if not row:
            return jsonify({'status': 'error', 'message': 'История не найдена'}), 500

        status = row[0]
        if status == 0:
            # === Считаем оставшиеся таски для этого заказа ===
            cursor.execute("""
                SELECT COUNT(*)
                  FROM DITE_DeliveriesTasks
                 WHERE ID_Orders     = ?
                   AND ID_Deliveries = ?
                   AND (Status     IS NULL OR Status = '')
                   AND WhoConfrim   IS NULL
                   AND DateConfrim  IS NULL
                   AND TimeConfrim  IS NULL
            """, (id_orders, id_deliveries))
            remaining = cursor.fetchone()[0] or 0

            # Возвращаем расширенный JSON
            return jsonify({
                'status':          'success',
                'scanned_count':   counts,          # или scanned — как у вас называется
                'remaining_tasks': remaining,
                'order_id':        id_orders,
                'id_deliveries':   id_deliveries
            }), 200
        else:
            return jsonify({'status': 'error', 'message': 'Задача не была успешно обновлена'}), 500

    except Exception as e:
        conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        conn.close()

def get_remaining_tasks_count(order_id, delivery_id):
    """
    Открывает своё подключение и возвращает количество незавершённых тасков
    для конкретного заказа+документа.
    """
    conn2 = connect_to_db()
    if not conn2:
        return 0
    try:
        cur2 = conn2.cursor()
        cur2.execute("""
            SELECT COUNT(*)
              FROM DITE_DeliveriesTasks
             WHERE ID_Orders     = ?
               AND ID_Deliveries = ?
               AND (LTRIM(RTRIM(ISNULL(Status,''))) = '')
               AND WhoConfrim   IS NULL
               AND DateConfrim  IS NULL
               AND TimeConfrim  IS NULL
        """, (order_id, delivery_id))
        return cur2.fetchone()[0] or 0
    finally:
        conn2.close()


@app.route('/shop_queue', methods=['GET'])
def shop_queue():
    # 1) Авторизация
    if 'who' not in session:
        return redirect(url_for('login'))

    turn = 'На МП'
    who  = session['who']

    conn = connect_to_db()
    cursor = conn.cursor()
    try:
        # 2) Мониторинг очереди (ServiceBroker)
        cursor.execute(
            "EXEC [u1603085_Maxim].[pr2_Мониторинг_Очереди_Copy] @Turn = ?, @Who = ?",
            (turn, who)
        )
        # собрать первый SELECT
        while cursor.description is None:
            if not cursor.nextset():
                break
        row = cursor.fetchone()
        if not row:
            flash(f"В очереди «{turn}» больше нет заданий.", "info")
            return redirect(url_for('queues'))

        columns     = [col[0] for col in cursor.description]
        data        = dict(zip(columns, row))
        order_id    = data['ID']
        delivery_id = data['ID_Deliveries']

        # 3) Выбираем все незавершённые задачи
        cursor.execute("""
            SELECT
              ID, Types, Froms, Tho, Articul, HS, Sizes, Heights, HeightsRus, Counts
            FROM DITE_DeliveriesTasks
            WHERE ID_Deliveries = ? AND ID_Orders = ?
              AND LTRIM(RTRIM(ISNULL(Status,''))) = ''
              AND WhoConfrim IS NULL
              AND DateConfrim IS NULL
              AND TimeConfrim IS NULL
        """, (delivery_id, order_id))
        rows = cursor.fetchall()
        if not rows:
            flash('Все задачи выполнены.', 'success')
            return redirect(url_for('order_details',
                                     order_id=order_id,
                                     id_deliveries=delivery_id))

        # Собираем список тасков и сортируем
        tasks = []
        for r in rows:
            tasks.append({
                'task_number': r[0],
                'types':       r[1],
                'from_cell':   r[2],
                'target_cell': r[3],
                'articul':     r[4],
                'hs':          r[5],
                'sizes':       r[6],
                'heights':     r[7],
                'heightsrus':  r[8],
                'counts':      r[9],
                'id_orders':   order_id,
                'id_deliveries': delivery_id
            })
        tasks.sort(key=lambda t: str(t['articul']))

        # 4) Инициализация и обработка очереди в сессии
        qkey = 'shop_queue'
        if qkey not in session or len(session[qkey]) != len(tasks):
            session[qkey] = [t['task_number'] for t in tasks]
        queue = session[qkey]

        skip_id = request.args.get('skip', type=int)
        if skip_id and skip_id in queue:
            queue.remove(skip_id)
            queue.append(skip_id)

        # Берём и удаляем из очереди следующий таск
        current_id = queue.pop(0)
        session[qkey] = queue
        task = next(t for t in tasks if t['task_number'] == current_id)

        # 5) Дополняем данными gender/model/color
        cursor.execute(
            "SELECT Gender, ID FROM DITE_Articuls WHERE Articul = ?",
            (task['articul'],)
        )
        art = cursor.fetchone()
        gender, id_art = (art[0], art[1]) if art else ('', None)
        model, color = '', ''
        if id_art:
            cursor.execute(
                "SELECT Models, ID FROM DITE_Articuls_Models WHERE ID_Articuls = ?",
                (id_art,)
            )
            m = cursor.fetchone()
            if m:
                model, m_id = m
                cursor.execute(
                    "SELECT Color FROM DITE_Cloaths WHERE ID = ?",
                    (m_id,)
                )
                c = cursor.fetchone()
                color = c[0] if c else ''
        task.update({'gender': gender, 'model': model, 'color': color})

        # 6) Считаем, сколько ещё осталось
        remaining = get_remaining_tasks_count(order_id, delivery_id)

        # 7) Берём правильный номер поставки из связующей таблицы
        cursor.execute("""
            SELECT ID_DeliveriesMP
            FROM DITE_Deliveries_MPArticulsToPositions_v2
            WHERE ID_Task = ?
        """, (task['task_number'],))
        mp = cursor.fetchone()
        task['doc'] = mp[0] if mp else delivery_id

        # 8) Сохраняем в сессии для /print_box
        session['shop_queue_task'] = task

        return render_template(
            'shop_queue.html',
            task=task,
            queue=turn,
            remaining_tasks=remaining
        )

    except Exception as e:
        logger.exception("shop_queue: ошибка")
        return f"Ошибка: {e}", 500

    finally:
        conn.close()



# 1) Проверка ячейки «Откуда»
@app.route('/shop_queue/validate_source', methods=['POST'])
def shop_queue_validate_source():
    data = request.get_json() or {}
    cell = data.get('cell_code')
    task_id = data.get('task_id')
    if not cell or not task_id:
        return jsonify({'status':'error','message':'Нет данных для проверки'}), 400

    conn = connect_to_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT Froms FROM DITE_DeliveriesTasks WHERE ID = ?",
            (task_id,)
        )
        row = cursor.fetchone()
        if not row or row[0] != cell:
            return jsonify({'status':'error','message':'Неверная ячейка «Откуда»'}), 400
        return jsonify({'status':'success'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'status':'error','message':str(e)}), 500
    finally:
        conn.close()


# 2) Сканирование товара по штрихкоду
@app.route('/shop_queue/scan', methods=['POST'])
def shop_queue_scan():
    data = request.get_json() or {}
    code = data.get('code', '').strip()
    step = data.get('step')                    # например, 'quantity' при вводе числа, но мы его игнорируем здесь
    task = session.get('shop_queue_task')
    if not task:
        return jsonify({'status':'error','message':'Нет активной задачи'}), 400
    if not code:
        return jsonify({'status':'error','message':'Нет кода'}), 400

    conn = connect_to_db()
    try:
        cursor = conn.cursor()

        # 1) Пытаемся считать как товар
        cursor.execute(
            "SELECT Articul, HS FROM DITE_Articuls_LabelsPrint WHERE QrCode = ?",
            (code,)
        )
        row = cursor.fetchone()
        if row:
            articul, hs = row
            # проверяем, что скан соответствует заданию
            if articul != task['articul'] or hs != task['hs']:
                return jsonify({'status':'error','message':'Неверный товар'}), 400
            scanned = session.get('scanned_items', [])
            # проверка на дублирование
            if any(it['qrcode'] == code for it in scanned):
                return jsonify({'status':'error','message':'Товар уже сканирован'}), 400
            now = datetime.now()
            scanned.append({
                'qrcode':    code,
                'articul':   articul,
                'hs':        hs,
                'box':       None,
                'date_scan': now.strftime("%Y-%m-%d"),
                'time_scan': now.strftime("%H:%M:%S")
            })
            session['scanned_items'] = scanned
            return jsonify({
                'status':'success',
                'type':'item',
                'record': scanned[-1],
                'items': scanned
            }), 200

        # 2) Если не товар — пробуем считать как коробку
        cursor.execute(
            "SELECT ID, ID_DeliveriesMP, NumCase FROM DITE_Deliveries_MPCase_v2 WHERE InnerBarcode = ?",
            (code,)
        )
        row = cursor.fetchone()
        if row:
            box_id, mp_id, num_case = row
            # проверяем, что коробка из той же поставки
            if mp_id != task['doc']:
                return jsonify({'status':'error','message':'Коробка не из текущей поставки'}), 400
            scanned = session.get('scanned_items', [])
            # присваиваем коробку всем ранее отсканированным товарам без box
            for itm in scanned:
                if itm.get('box') is None:
                    itm['box']     = code
                    itm['case_id'] = box_id
                    itm['num_case']= num_case
            session['scanned_items'] = scanned
            return jsonify({
                'status':'success',
                'type':'box',
                'record': {'boxId': box_id, 'innerBarcode': code, 'caseNum': num_case},
                'items': scanned
            }), 200

        # 3) Если ни товар, ни коробка
        return jsonify({'status':'error','message':'Неподдерживаемый штрихкод'}), 400

    except Exception as e:
        conn.rollback()
        return jsonify({'status':'error','message': str(e)}), 500

    finally:
        conn.close()




# 3) Текущее значение счётчика сканирований
@app.route('/shop_queue/scanned_count', methods=['GET'])
def shop_queue_scanned_count():
    return jsonify({'scanned_count': session.get('scanned_count', 0)}), 200

# 4) Проверка штрихкода целевой коробки
@app.route('/shop_queue/validate_target_box', methods=['POST'])
def shop_queue_validate_target_box():
    data = request.get_json() or {}
    cell = data.get('cell_code')
    task_id = data.get('task_id')
    if not cell or not task_id:
        return jsonify({'status':'error','message':'Нет данных для проверки'}), 400

    conn = connect_to_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT Tho FROM DITE_DeliveriesTasks WHERE ID = ?",
            (task_id,)
        )
        row = cursor.fetchone()
        if not row or row[0] != cell:
            return jsonify({'status':'error','message':'Неверная коробка «Куда»'}), 400
        return jsonify({'status':'success'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'status':'error','message':str(e)}), 500
    finally:
        conn.close()

# 5) Обновление задачи после сканирования











@app.route('/shop_queue/print_box', methods=['POST'])
def shop_queue_print_box():
    data = request.get_json() or {}
    count = int(data.get('count', 1))
    task  = session.get('shop_queue_task')
    if not task or 'doc' not in task:
        return jsonify({'error':'Нет номера поставки'}), 400

    conn = connect_to_db()
    try:
        cur = conn.cursor()
        now = datetime.now()
        cur.execute("""
            INSERT INTO DITE_Queue_CasePrint_copy1
              (NumDocument, TypeDocument, CountCase, WhoPrint, DatePrint, TimePrint)
            VALUES (?, 'МП', ?, ?, ?, ?)
        """, (
            task['doc'],
            count,
            session['who'],
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M:%S"),
        ))
        conn.commit()
        return jsonify({'status':'success'}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500

    finally:
        conn.close()





@app.route('/shop_queue/status', methods=['GET'])
def shop_queue_status():
    scanned = session.get('scanned_items', [])
    return jsonify({'items': scanned})



@app.route('/shop_queue/update_task', methods=['POST'])
def shop_queue_update_task():
    task  = session.get('shop_queue_task')
    items = session.get('scanned_items', [])
    cases = session.get('shop_queue_cases', [])
    if not task or not items or not cases:
        return jsonify({'status':'error','message':'Нет данных'}), 400

    conn = connect_to_db()
    try:
        cur = conn.cursor()
        scans = session.get('scanned_items', [])
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")

        # 1) Обновляем задачу
        cur.execute("""
            EXEC [u1603085_Maxim].[pr2_ServiceBroker_СкладскаяЗадача_Очередь_ОбновитьЗадачу]
                @idTask=?, @whoUpdate=?, @whoIdUpdate=?, @counts=?, @dateUpdate=?, @timeUpdate=?
        """, (
            task['task_number'], session['who'], session['who_id'],
            len(items), date_str, time_str
        ))

        # 2) Вставляем в DITE_Deliveries_MPArticulsToTPositionsCase_v2
        from collections import defaultdict
        groups = defaultdict(int)
        for itm in items:
            groups[itm['box']] += 1

        for box_barcode, cnt in groups.items():
            # находим ID коробки
            cur.execute(
                "SELECT ID FROM DITE_Queue_CasePrint WHERE InnerBarcode = ?",
                (box_barcode,)
            )
            row = cur.fetchone()
            id_case = row[0] if row else None

            cur.execute("""
                INSERT INTO DITE_Deliveries_MPArticulsToTPositionsCase_v2
                  (Counts, ID_Case, WhoCreate, DateCreate, TimeCreate,
                   ID_DeliveriesMP, ID_Task)
                VALUES (?,    ?,       ?,         ?,          ?, 
                        ?,              ?)
            """, (
                cnt, id_case, session['who'],
                date_str, time_str,
                task['id_deliveries'],  # номер поставки
                task['task_number']
            ))
        for scan in scans:
            cur.execute("""
                INSERT INTO DITE_DeliveriesTasksScans
                (QrCode, DateScan, TimeScan, TimeFact, ID_Task, ID_Orders, ID_Deliveries)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                scan['qrcode'],              # отсканированный QR-код товара
                scan['date_scan'],           # дата скана из session
                scan['time_scan'],           # время скана из session
                now.strftime("%H:%M:%S"),    # фактическое время логирования
                task['task_number'],         # ID задачи
                task['id_orders'],           # ID заказа
                task['id_deliveries']        # ID поставки
            ))
        # 3) Коммит всех изменений
        conn.commit()
        

        # Сбросим сессионные данные
        session.pop('scanned_items', None)
        session.pop('shop_queue_cases', None)

        return jsonify({'status':'success'}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({'status':'error','message':str(e)}), 500

    finally:
        conn.close()



@app.route('/shop_queue/delete', methods=['POST'])
def delete_scanned_item():
    index = request.get_json().get('index')
    scanned = session.get('scanned_items', [])
    try:
        index = int(index)
        if 0 <= index < len(scanned):
            scanned.pop(index)
            session['scanned_items'] = scanned
    except:
        pass
    return jsonify({'items': scanned})


import logging

logger = logging.getLogger(__name__)

import pyodbc   # вверху файла, рядом с другими импортами

@app.route('/split_order', methods=['POST'])
def split_order():
    # 0) Авторизация
    if 'who' not in session:
        return redirect(url_for('login'))

    # 1) Чтение параметров
    order_id = request.form.get('order_id', type=int)
    turn     = request.form.get('turn',     type=str)
    who      = session['who']
    if not order_id or not turn:
        logger.error("split_order: неверные параметры order_id=%r turn=%r", 
                     order_id, turn)
        return "Ошибка: не задан order_id или очередь", 400

    conn   = connect_to_db()
    cursor = conn.cursor()

    try:
        # 2) Собираем ВСЕ незавершённые таски
        cursor.execute("""
            SELECT STRING_AGG(CAST(ID AS VARCHAR(MAX)), ',')
              FROM DITE_DeliveriesTasks
             WHERE ID_Orders = ?
               AND (Status      IS NULL OR Status      = '')
               AND  WhoConfrim  IS NULL
               AND  DateConfrim IS NULL
               AND  TimeConfrim IS NULL
        """, (order_id,))
        tasks_list = cursor.fetchone()[0] or ''
        logger.info("split_order: tasks_list=%r", tasks_list)

        # 3) Передаём их в pr2_СкладЗаказРазделить
        cursor.execute("""
            DECLARE @out INT;
            EXEC [u1603085_Maxim].[pr2_СкладЗаказРазделить]
                @who      = ?,
                @listTask = ?,
                @IDlist   = @out OUTPUT;
        """, (who, tasks_list))
        conn.commit()

        # 4) Снимаем бронь
        cursor.execute("""
            UPDATE DITE_DeliveriesOrders
               SET WhoReserved  = NULL,
                   DateReserved = NULL,
                   TimeReserved = NULL
             WHERE ID = ? AND WhoReserved = ?
        """, (order_id, who))
        conn.commit()

        # 5) Мониторим очередь — пропускаем непро-SELECT наборы
        cursor.execute(
            "EXEC [u1603085_Maxim].[pr2_Мониторинг_Очереди_Copy] @Turn = ?, @Who = ?",
            (turn, who)
        )
        while cursor.description is None:
            if not cursor.nextset():
                break
        try:
            row2 = cursor.fetchone()
        except pyodbc.ProgrammingError:
            row2 = None

        if row2:
            next_row = dict(zip([c[0] for c in cursor.description], row2))
        else:
            next_row = None

    except Exception as e:
        logger.exception("split_order: ошибка")
        # не закрываем тут conn — закроет finally
        return str(e), 500

    finally:
        conn.close()

    # 6) Редирект
    if next_row and 'ID' in next_row:
        # Есть следующий заказ в очереди — открываем его детали
        return redirect(url_for('order_details',
                                order_id=next_row['ID'],
                                id_deliveries=next_row['ID_Deliveries'],
                                queue=turn))
    else:
        # Заказов в этой очереди больше нет — возвращаемся к списку очередей
        return redirect(url_for('queues'))








from flask import jsonify

@app.route('/clear_scans', methods=['POST'])
def clear_scans():
    if 'who' not in session:
        return jsonify(success=False), 401

    # 1) Сбрасываем прогресс
    session['scanned_count'] = 0
    session.pop('scanned_items', None)

    # 2) Отдаём подтверждение клиенту
    return jsonify(success=True)



@app.route('/logout')
def logout():
    session.clear()  # очищаем все данные сессии
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)


