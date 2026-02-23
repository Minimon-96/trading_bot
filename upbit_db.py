import pymysql
import time
import pyupbit

# MySQL 서버에 연결
conn = pymysql.connect(
    host="localhost",
    user="root",
    #password="1234",
    password="root1234",
    database="test"
)

tickers = ["KRW-BTC", "KRW-XRP", "KRW-ETH" ]

def tb_upbit():
    print("1")
    # 데이터베이스 커서 생성
    cursor = conn.cursor()

    price = {'KRW-BTC' : 0, 'KRW-ETH' : 0, 'KRW-XRP' : 0}
    while True:
        try:
            # 데이터 INSERT
            for i in tickers:
                price = pyupbit.get_current_price(i)
                sql_insert = "INSERT INTO upbit_tbl (name, price) VALUES (%s, %s)"
                values = (i, price)
                cursor.execute(sql_insert, values)
            # 변경 사항을 커밋
            conn.commit()
            time.sleep(3)
        except Exception as e:
            print("에러 발생:", e)
    # 커서와 연결 종료
    cursor.close()

# 예외 처리 추가
try:
    tb_upbit()
except KeyboardInterrupt:
    pass

# MySQL 연결 종료
conn.close()



"""
# Table 생성
mysql> CREATE TABLE upbit_tbl (
    id INT(11) NOT NULL AUTO_INCREMENT,
    name VARCHAR(8) DEFAULT NULL,
    price FLOAT DEFAULT NULL,
    time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
);

# Table 정보
mysql> desc upbit_tbl;
+-------+------------+------+-----+-------------------+-----------------------------------------------+
| Field | Type       | Null | Key | Default           | Extra                                         |
+-------+------------+------+-----+-------------------+-----------------------------------------------+
| id    | int        | NO   | PRI | NULL              | auto_increment                                |
| name  | varchar(8) | YES  |     | NULL              |                                               |
| price | float      | YES  |     | NULL              |                                               |
| time  | timestamp  | NO   |     | CURRENT_TIMESTAMP | DEFAULT_GENERATED on update CURRENT_TIMESTAMP |
+-------+------------+------+-----+-------------------+-----------------------------------------------+

# Table 내용 조회
mysql> select * from upbit_tbl;
+----+---------+----------+---------------------+
| id | name    | price    | time                |
+----+---------+----------+---------------------+
|  1 | KRW-BTC | 37977000 | 2023-07-31 04:31:45 |
|  2 | KRW-XRP |      926 | 2023-07-31 04:31:45 |
|  3 | KRW-ETH |  2431000 | 2023-07-31 04:31:45 |
...
| 13 | KRW-BTC | 37977000 | 2023-07-31 04:32:38 |
| 14 | KRW-XRP |      925 | 2023-07-31 04:32:38 |
| 15 | KRW-ETH |  2431000 | 2023-07-31 04:32:38 |
+----+---------+----------+---------------------+

# Table 특정 name 필드값에 대한 넘버링 조회
mysql> SELECT ROW_NUMBER() OVER (PARTITION BY name ORDER BY time) AS num, name, price, time
FROM upbit_tbl
WHERE name = 'KRW-XRP';
+-----+---------+-------+---------------------+
| num | name    | price | time                |
+-----+---------+-------+---------------------+
|   1 | KRW-XRP |   926 | 2023-07-31 04:31:45 |
|   2 | KRW-XRP |   926 | 2023-07-31 04:32:29 |
|   3 | KRW-XRP |   926 | 2023-07-31 04:32:32 |
|   4 | KRW-XRP |   925 | 2023-07-31 04:32:35 |
|   5 | KRW-XRP |   925 | 2023-07-31 04:32:38 |
+-----+---------+-------+---------------------+

# 테이블 초기화
mysql> DELETE FROM upbit_tbl;
mysql> ALTER TABLE upbit_tbl AUTO_INCREMENT = 1;
mysql> commit;

"""