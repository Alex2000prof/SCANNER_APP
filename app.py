import os
import logging
from datetime import datetime

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
    mode = request.args.get('mode')
    if 'who' not in session:
        return redirect(url_for('login'))
    
    conn = connect_to_db()
    if not conn:
        return "Ошибка подключения к БД", 500

    try:
        cursor = conn.cursor()
        # -- A. Вызываем вашу процедуру мониторинга очереди
        # -- A. Вызываем вашу процедуру мониторинга очереди
        if mode == 'marketplace':
            sql = "EXEC [u1603085_Maxim].[pr2_Мониторинг_Очереди_Copy] @Turn = ?, @Mode = ?"
            cursor.execute(sql, (turn, mode))
        else:
            sql = "EXEC [u1603085_Maxim].[pr2_Мониторинг_Очереди_Copy] @Turn = ?"
            cursor.execute(sql, (turn,))

        
        # Пропускаем промежуточные результаты, пока не найдём строку
        while True:
            row = cursor.fetchone()
            if row is not None:
                break
            if not cursor.nextset():
                break

        if not row:
            return f"Нет данных по очереди '{turn}'", 404

        columns = [col[0] for col in cursor.description]
        order_data = dict(zip(columns, row))

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

        if ('LM' in inputs_value) or ('WB' in inputs_value):
            # 1) Берём ID_Deliveries
            id_deliveries = order_data.get('ID_Deliveries')
            if id_deliveries:
                # 2) Ищем любой (TOP 1) складской задачи в DITE_DeliveriesTask (там ID_Deliveries)
                cursor.execute("""
                    SELECT TOP 1 ID
                    FROM DITE_DeliveriesTasks
                    WHERE ID_Deliveries = ?
                """, (id_deliveries,))
                row_task = cursor.fetchone()
                if row_task:
                    id_task = row_task[0]
                    # 3) Идём в DITE_Deliveries_MPArticulsToPositions_v2 (там поле ID_Task)
                    cursor.execute("""
                        SELECT TOP 1 ID_DeliveriesMP
                        FROM DITE_Deliveries_MPArticulsToPositions_v2
                        WHERE ID_Task = ?
                    """, (id_task,))
                    row_mp = cursor.fetchone()
                    if row_mp:
                        # 4) Сохраняем номер поставки
                        order_data['NumPostavki'] = row_mp[0]

        # Передаём все данные в шаблон
        return render_template('order_details.html', order=order_data, queue=turn)

    except Exception as e:
        return str(e), 500
    finally:
        conn.close()


@app.route('/print_document', methods=['GET'])
def print_document():
    if 'who' not in session:
        return redirect(url_for('login'))
    
    # Из GET-параметров получаем ID_Deliveries и очередь
    id_deliveries = request.args.get('id_deliveries')
    queue = request.args.get('queue')
    if not id_deliveries:
        return "Не указан документ", 400

    conn = connect_to_db()
    if not conn:
        return "Ошибка подключения к БД", 500

    try:
        cursor = conn.cursor()
        # 1. Выбираем все складские задачи из DITE_DeliveriesTasks,
        # где ID_Deliveries = id_deliveries и поля WhoConfirm, DateConfirm, TimeConfirm равны NULL.
        cursor.execute("""
            SELECT ID, Tho
            FROM DITE_DeliveriesTasks
            WHERE ID_Deliveries = ?
              AND WhoConfrim IS NULL AND DateConfrim IS NULL AND TimeConfrim IS NULL
        """, (id_deliveries,))
        tasks = cursor.fetchall()
        if not tasks:
            return "Нет задач для печати", 404

        who_create = session.get('who')
        now = datetime.now()
        date_create = now.strftime('%Y-%m-%d')
        time_create = now.strftime('%H:%M:%S')
        inserted_count = 0

        for task in tasks:
            id_task = task[0]
            tho = task[1]  # Значение поля Tho из DITE_DeliveriesTasks

            # 2. Получаем Store:
            # Из таблицы DITE_DivisionsPlaces ищем запись, где Place = tho
            # и извлекаем поле ID_Division.
            cursor.execute("""
                SELECT TOP 1 ID_Division 
                FROM DITE_DivisionsPlaces
                WHERE Place = ?
            """, (tho,))
            row_place = cursor.fetchone()
            store = row_place[0] if row_place else None

            # 3. Определяем Group по логике:
            if queue == "Перемещение":
                group = "Перемещение"
            elif queue == "Приёмка":
                group = "Документ"
            elif queue == "На магазин":
                # Если в Tho содержится LM или WB, то Group = "МП", иначе "Магазин"
                if ("LM" in tho) or ("WB" in tho):
                    group = "МП"
                else:
                    group = "Магазин"
            else:
                group = ""

            # 4. Вставляем строку в DITE_Queue_TaskPrint:
            cursor.execute("""
                INSERT INTO DITE_Queue_TaskPrint (id_task, WhoCreate, DateCreate, TimeCreate, Store, [Group])
                VALUES (?, ?, ?, ?, ?, ?)
            """, (id_task, who_create, date_create, time_create, store, group))
            inserted_count += 1

        conn.commit()
        # Можно выполнить редирект или вернуть сообщение
        return f"Печатный документ сформирован. Вставлено строк: {inserted_count}"
    except Exception as e:
        conn.rollback()
        logger.exception("Ошибка при формировании печатного документа:")
        return str(e), 500
    finally:
        conn.close()


from flask import Flask, request, jsonify, render_template, session, redirect, url_for


def split_cell(cell: str):
    """
    Парсит строку 'AAA-BB-CC' в (AAA,BB,CC),
    на невалидных возвращает (999,999,999).
    """
    try:
        sec  = int(cell[0:3])
        rack = int(cell[4:6])
        pos  = int(cell[7:9])
    except:
        return (999, 999, 999)
    return (sec, rack, pos)




from datetime import datetime, date, time

def serialize_dict(d):
    """Преобразует значения типа datetime, date, time в строки для корректной сериализации."""
    new_d = {}
    for k, v in d.items():
        if isinstance(v, (datetime, )):
            new_d[k] = str(v)
        else:
            new_d[k] = v
    return new_d

sector_neighbors = {
    102: [103],
    103: [102],
    104: [105],
    105: [104],
    106: [107],
    107: [106],
    108: [109],
    109: [108],
    110: [111],
    111: [110],
    112: [113],
    113: [112],
    114: [115],
    115: [114],
    118: [119],
    119: [118],
    
    201: [202],
    202: [201],
    203: [204],
    204: [203],
    205: [206],
    206: [205],
    207: [208],
    208: [207],
    209: [210],
    210: [209],
    211: [212],
    212: [211],
    213: [214],
    214: [213],
}


@app.route('/transfer', methods=['GET', 'POST'])
def transfer():
    who = session.get('who')
    if not who:
        return "Не авторизован", 401

    turn = 'Перемещение'
    mode = request.args.get('mode', 'default')
    skip_id = request.args.get('skip')

    conn = connect_to_db()
    if not conn:
        return "Ошибка подключения к базе данных", 500

    try:
        cursor = conn.cursor()
        session['scanned_count'] = 0
        cursor.execute("EXEC [u1603085_Maxim].[pr2_Мониторинг_Очереди_Copy] @Turn=?, @Who=?", (turn, who))
        row = cursor.fetchone()
        if not row:
            session.pop('skipped_tasks', None)
            return "Нет заданий", 200

        id_orders     = row[0]
        id_deliveries = row[1]

        cursor.execute("""
            SELECT ID, Types, Froms, Tho, Articul, HS, Sizes, Heights, HeightsRus, Counts
            FROM DITE_DeliveriesTasks
            WHERE ID_Deliveries = ? AND ID_Orders = ?
              AND ISNULL(Status, '') = ''
              AND ISNULL(WhoConfrim, '') = ''
              AND ISNULL(DateConfrim, '') = ''
              AND ISNULL(TimeConfrim, '') = ''
        """, (id_deliveries, id_orders))
        rows = cursor.fetchall()
        if not rows:
            session.pop('skipped_tasks', None)
            return "Все задачи уже выполнены", 200

        # Обработка skip до сортировки
        if skip_id:
            try:
                skip_id = int(skip_id)
                skipped = session.get('skipped_tasks', [])
                if skip_id not in skipped:
                    skipped.append(skip_id)
                    session['skipped_tasks'] = skipped
            except:
                pass

        skipped = session.get('skipped_tasks', [])

        def parse_cell(cell):
            try: return int(cell[0:3]), int(cell[4:6]), int(cell[7:9])
            except: return 999, 999, 999

        def floor(cell):
            try: return int(cell[0:3])
            except: return 0

        def is_real(cell): return 100 <= floor(cell) <= 299
        def is_2nd(cell): return 200 <= floor(cell) < 300
        def is_1st(cell): return 100 <= floor(cell) < 200

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
                'id_deliveries': id_deliveries
            }
            if task['task_number'] not in skipped:
                tasks.append(task)

        # === СОРТИРОВКА ===
        if mode == 'articul':
            ordered = sorted(tasks, key=lambda t: str(t['articul']))
        else:
            grp_2to2, grp_2to1, grp_1to2, grp_other = [], [], [], []

            for t in tasks:
                from2, to2 = is_2nd(t['from_cell']), is_2nd(t['target_cell'])
                from1, to1 = is_1st(t['from_cell']), is_1st(t['target_cell'])

                if from2 and to2:
                    grp_2to2.append(t)
                elif from2 and to1:
                    grp_2to1.append(t)
                elif from1 and to2:
                    grp_1to2.append(t)
                else:
                    grp_other.append(t)

            def distance(t, base):
                sec0, rack0, pos0 = parse_cell(base)
                sec1, rack1, pos1 = parse_cell(t['from_cell'])

                sector_penalty = 0
                if sec0 != sec1:
                    if sec1 not in sector_neighbors.get(sec0, []):
                        sector_penalty = 100  # Штраф если сектора не соседние
                    # иначе штрафа нет, если соседние

                return abs(rack0 - rack1) + abs(pos0 - pos1) + sector_penalty



            def sort_by_nearest(group, from_cell):
                return sorted(group, key=lambda t: distance(t, from_cell))

            ordered = []

            if grp_2to2:
                current = sort_by_nearest(grp_2to2, "200-01-01")[0]
                grp_2to2.remove(current)
                ordered.append(current)
                while grp_2to2:
                    current = sort_by_nearest(grp_2to2, current['target_cell'])[0]
                    grp_2to2.remove(current)
                    ordered.append(current)

            grp_2to1 = sort_by_nearest(grp_2to1, ordered[-1]['target_cell'] if ordered else "200-01-01")
            grp_1to2 = sort_by_nearest(grp_1to2, grp_2to1[-1]['target_cell'] if grp_2to1 else "200-01-01")

            for i in range(max(len(grp_2to1), len(grp_1to2))):
                if i < len(grp_2to1): ordered.append(grp_2to1[i])
                if i < len(grp_1to2): ordered.append(grp_1to2[i])

            grp_other = sort_by_nearest(grp_other, ordered[-1]['target_cell'] if ordered else "200-01-01")
            ordered.extend(grp_other)

        if not ordered:
            session.pop('skipped_tasks', None)
            return "Нет задач", 200

        t = ordered[0]

        # Инфо по артикулу
        cursor.execute("SELECT Gender, ID FROM DITE_Articuls WHERE Articul = ?", (t['articul'],))
        row = cursor.fetchone()
        if row and len(row) >= 2:
            gender = row[0]
            id_articul = row[1]
        else:
            gender = ""
            id_articul = None

        model, id_model, color = "", None, ""
        if id_articul:
            cursor.execute("SELECT Models, ID FROM DITE_Articuls_Models WHERE ID_Articuls = ?", (id_articul,))
            row = cursor.fetchone()
            if row and len(row) >= 2:
                model, id_model = row[0], row[1]
                cursor.execute("SELECT Color FROM DITE_Cloaths WHERE ID = ?", (id_model,))
                row = cursor.fetchone()
                color = row[0] if row else ""

        task = t.copy()
        task.update({
            'gender': gender,
            'model': model,
            'color': color,
            'remaining_tasks': len(ordered)
        })

        return render_template("transfer.html", task=task)

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
        scanned = session.get('scanned_count', 0) + 1
        session['scanned_count'] = scanned

        # 6) Возвращаем обновлённый счётчик
        return jsonify({
            'status': 'success',
            'scanned_count': scanned
        }), 200

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
            return jsonify({'status': 'success'})
        else:
            return jsonify({'status': 'error', 'message': 'Задача не была успешно обновлена'})

    except Exception as e:
        conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        conn.close()




@app.route('/shop_queue', methods=['GET', 'POST'])
def shop_queue():
    who = session.get('who')
    if not who:
        return "Не авторизован", 401

    turn = 'На магазин'
    mode = request.args.get('mode', 'default')
    if request.method == 'GET' and mode:
        session['shop_queue_mode'] = mode
    mode = session.get('shop_queue_mode', 'default')
    skip_id = request.args.get('skip')

    conn = connect_to_db()
    if not conn:
        return "Ошибка подключения к базе данных", 500

    try:
        cursor = conn.cursor()
        session['scanned_count'] = 0

        if mode == 'marketplace':
            cursor.execute("EXEC [u1603085_Maxim].[pr2_Мониторинг_Очереди_Copy] @Turn=?, @Who=?, @Mode=?", (turn, who, mode))
        else:
            cursor.execute("EXEC [u1603085_Maxim].[pr2_Мониторинг_Очереди_Copy] @Turn=?, @Who=?", (turn, who))

        row = cursor.fetchone()
        if not row:
            session.pop('skipped_tasks', None)
            return "Нет заданий", 200

        id_orders     = row[0]
        id_deliveries = row[1]

        cursor.execute("""
            SELECT ID, Types, Froms, Tho, Articul, HS, Sizes, Heights, HeightsRus, Counts
            FROM DITE_DeliveriesTasks
            WHERE ID_Deliveries = ? AND ID_Orders = ?
              AND ISNULL(Status, '') = ''
              AND ISNULL(WhoConfrim, '') = ''
              AND ISNULL(DateConfrim, '') = ''
              AND ISNULL(TimeConfrim, '') = ''
        """, (id_deliveries, id_orders))
        rows = cursor.fetchall()


        if not rows:
            session.pop('skipped_tasks', None)
            return "Все задачи уже выполнены", 200

        tasks = []
        valid_tasks = []
        for row in rows:
            task_id = row[0]

            # Проверяем наличие в DITE_Deliveries_MPArticulsToPositions_v2
            cursor.execute("""
                SELECT COUNT(*)
                FROM DITE_Deliveries_MPArticulsToPositions_v2
                WHERE ID_Task = ?
            """, (task_id,))
            exists = cursor.fetchone()[0]

            if exists == 0:
                continue  # Пропускаем эту задачу

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
                'id_deliveries': id_deliveries
            }
            valid_tasks.append(task)


        if not valid_tasks:
            return "Нет задач", 200

        t = valid_tasks[0]


        # Инфо по артикулу (как в transfer)
        cursor.execute("SELECT Gender, ID FROM DITE_Articuls WHERE Articul = ?", (t['articul'],))
        row = cursor.fetchone()
        gender = row[0] if row else ""
        id_articul = row[1] if row else None

        model, color = "", ""
        if id_articul:
            cursor.execute("SELECT Models, ID FROM DITE_Articuls_Models WHERE ID_Articuls = ?", (id_articul,))
            row = cursor.fetchone()
            if row:
                model = row[0]
                id_model = row[1]
                cursor.execute("SELECT Color FROM DITE_Cloaths WHERE ID = ?", (id_model,))
                row = cursor.fetchone()
                color = row[0] if row else ""

        task = t.copy()
        task.update({
            'gender': gender,
            'model': model,
            'color': color,
            'remaining_tasks': len(valid_tasks)
        })

        return render_template("shop_queue.html", task=task)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"Ошибка: {e}", 500
    finally:
        conn.close()





def get_remaining_tasks_count(conn, id_orders, id_deliveries):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*)
        FROM DITE_DeliveriesTasks
        WHERE ID_Deliveries = ?
          AND ID_Orders = ?
          AND ISNULL(Status, '') = ''
          AND ISNULL(WhoConfrim, '') = ''
          AND ISNULL(DateConfrim, '') = ''
          AND ISNULL(TimeConfrim, '') = ''
    """, (id_deliveries, id_orders))
    row = cursor.fetchone()
    return row[0] if row else 0






@app.route('/shop_queue/print_box', methods=['POST'])
def shop_queue_print_box():
    if 'who' not in session:
        return jsonify({'error': 'Не авторизован'}), 403

    data = request.get_json()
    count = int(data.get('count', 1))
    task = session.get('shop_queue_task')
    if not task:
        return jsonify({'error': 'Нет задачи'}), 400

    conn = connect_to_db()
    try:
        cursor = conn.cursor()
        now = datetime.now()
        cursor.execute("""
            INSERT INTO DITE_Queue_CasePrint
            (NumDocument, TypeDocument, CountCase, Who, DatePrint, TimePrint)
            VALUES (?, 'МП', ?, ?, ?, ?)
        """, (
            task['doc'],
            count,
            session['who'],
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M:%S")
        ))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()



@app.route('/shop_queue/status', methods=['GET'])
def shop_queue_status():
    scanned = session.get('scanned_items', [])
    return jsonify({'items': scanned})


@app.route('/shop_queue/scan', methods=['POST'])
def shop_queue_scan():
    data = request.get_json()
    code = data.get('code', '').strip()
    who = session.get('who', 'UNKNOWN')

    if not code:
        return jsonify({'status': 'error', 'message': 'Нет кода'}), 400

    conn = connect_to_db()
    if not conn:
        return jsonify({'status': 'error', 'message': 'Нет подключения к БД'}), 500

    cursor = conn.cursor()
    try:
        scanned = session.get('scanned_items', [])

        if '-' in code and code.count('-') == 1:  # коробка
            # Присваиваем всем без box
            for item in scanned:
                if item.get('box') is None:
                    item['box'] = code
            session['scanned_items'] = scanned
            return jsonify({'status': 'success', 'message': 'Коробка присвоена', 'items': scanned})

        else:  # товар
            # Получаем Articul и HS
            cursor.execute("""
                SELECT Articul, HS
                FROM DITE_Articuls_LabelsPrint
                WHERE QrCode = ?
            """, (code,))
            row = cursor.fetchone()
            if not row:
                return jsonify({'status': 'error', 'message': 'QR-код не найден в БД'}), 400

            articul, hs = row
            # Проверка на дубли
            for item in scanned:
                if item['qrcode'] == code:
                    return jsonify({'status': 'error', 'message': 'Этот товар уже сканирован'}), 400

            scanned.append({
                'qrcode': code,
                'articul': articul,
                'hs': hs,
                'box': None
            })
            session['scanned_items'] = scanned
            return jsonify({'status': 'success', 'message': 'Товар добавлен', 'items': scanned})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
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


@app.route('/logout')
def logout():
    session.clear()  # очищаем все данные сессии
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
