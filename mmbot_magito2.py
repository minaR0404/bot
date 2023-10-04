# Python3 MarketMaker(MM)BOTのサンプルロジックとソースコード（ https://note.com/magimagi1223/n/n5fba7501dcfd ）のコピペの改良版
# 両側の最良気配値付近の指値をブレイクした方向に順張りで指値を出す戦略
# 従来の両側の最良気配値に指値を置く戦略では、一方向に傾いて指値が置いていかれること（逆選択リスク）が多く、損失を出してしまったため。
# 数秒の短期間の価格形成には一定の方向感が存在する傾向があると思われる。


#!/usr/bin/python3
# coding: utf-8

import datetime
import time
import settings
import numpy as np

import ccxt
bitflyer = ccxt.bitflyer({
'apiKey': settings.AK,
'secret': settings.AS,
})

# 取引する通貨、シンボルを設定
COIN = 'BTC'
#PAIR = 'BTCJPY28SEP2018'
PAIR = 'FX_BTC_JPY'

# ロット(単位はBTC)
LOT = 0.01

# 最小注文数(取引所の仕様に応じて設定)
AMOUNT_MIN = 0.01

# スプレッド閾値
SPREAD_ENTRY = 0.0003  # 実効スプレッド(100%=1,1%=0.01)がこの値を上回ったらエントリー
SPREAD_CANCEL = 0.0001 # 実効スプレッド(100%=1,1%=0.01)がこの値を下回ったら指値更新を停止

# 数量X(この数量よりも下に指値をおく)
# AMOUNT_THRU = 0.01

X = 0.0
offset = 0.0

# 数量Xのリスト
x_list = [0,0,0,0,0]
std_list = [0,0,0,0,0]

side = None

# 実効Ask/BidからDELTA離れた位置に指値をおく
DELTA = 20   # 約定確率を上げるためにはスプを狭める

#------------------------------------------------------------------------------#
#log設定
import logging
logger = logging.getLogger('LoggingTest')
logger.setLevel(10)
#fh = logging.FileHandler('log_mm_bf_' + datetime.datetime.now().strftime('%Y%m%d') + '_' + datetime.datetime.now().strftime('%H%M%S') + '.log')
#logger.addHandler(fh)
sh = logging.StreamHandler()
logger.addHandler(sh)
formatter = logging.Formatter('%(asctime)s: %(message)s', datefmt="%Y-%m-%d %H:%M:%S")
#fh.setFormatter(formatter)
sh.setFormatter(formatter)

#------------------------------------------------------------------------------#

# JPY残高を参照する関数
def get_asset():

    while True:
        try:
            value = bitflyer.fetch_balance()
            break
        except Exception as e:
            logger.info(e)
            time.sleep(1)
    return value

# JPY証拠金を参照する関数
def get_colla():

    while True:
        try:
            value = bitflyer.privateGetGetcollateral()
            break
        except Exception as e:
            logger.info(e)
            time.sleep(1)
    return value

# 在庫管理として定期的にポジションを確認する関数
def get_position():
    global side
    while True:
        try:
            value = bitflyer.private_get_getpositions(params = {"product_code" : PAIR})
            break
        except Exception as e:
            logger.info(e)
            time.sleep(1)
    if not value:
        size = 0
        side = None
    if value:
        if value[0]["side"] == "BUY":
            side = "SELL"
        if value[0]["side"] == "SELL":
            side = "BUY"
        size = []
        for p in value:
            size.append(float(p["size"]))
        size = np.sum(size).round(8)
        if size < 0.01:
            size = 0
    return {"size":size, "side":side}

# 約定履歴から数量Xとオフセット値を計算する関数
def get_amount():
    global X
    global offset
    while True:
        try:
            exe_list = []
            exp_list = []
            try:
                execution = bitflyer.public_get_getexecutions(params = {"product_code" : "FX_BTC_JPY", "count" : 50})
            except Exception as e:
                logger.info(e)
                time.sleep(1)
            now_time = datetime.datetime.now() - datetime.timedelta(hours=9)

            for exe in execution:
                try:
                    exe_time = datetime.datetime.strptime(exe["exec_date"], '%Y-%m-%dT%H:%M:%S.%f')   # 文字列を時間に変換
                except Exception as e:
                    exe_time = datetime.datetime.strptime(exe["exec_date"], '%Y-%m-%dT%H:%M:%S')   # 稀にミリ秒以下が記述されない例外が存在

                if exe_time + datetime.timedelta(seconds=3) > now_time:   # 現在時刻から過去５秒間の約定量を計算
                    exe_list.append(float(exe["size"]))
                    exp_list.append(float(exe["price"]))
                else:
                    if len(exe_list) != 0:
                        x = np.sum(exe_list)
                        std = np.std(exp_list).round()
                        x_list.append(x)
                        std_list.append(std)
                    break

                X_list = []
                offset_list = []
                for i in range(5):
                    X_list.append(x_list[-1*i-1])
                    X = np.mean(X_list).round(2)
                    offset_list.append(std_list[-1*i-1])
                    offset = np.mean(offset_list).round()*2
        except Exception as e:
            logger.info(e)
            time.sleep(1)
        return {'X':X, 'offset':offset}

# 在庫リスクからオフセット値を決定する関数
def get_offset(offset, trade_ask, trade_bid):

    if trade_ask == 'open' and trade_bid == 'closed':
        Offset = -offset
    if trade_ask == 'closed' and trade_bid == 'open':
        Offset = offset
    if trade_ask == 'open' and trade_bid == 'open':
        Offset = 0.0
    if trade_ask == 'closed' and trade_bid == 'closed':
        Offset = 0.0
    return Offset

# 板情報から実効Ask/Bid(=指値を入れる基準値)を計算する関数
def get_effective_tick(size_thru, offset, rate_ask, size_ask, rate_bid, size_bid):

    while True:
        try:
            value = bitflyer.public_get_getboard(params = {"product_code" : PAIR})
            break
        except Exception as e:
            logger.info(e)
            time.sleep(2)

    size_thru = size_thru/2   # ask,bidで半分に分ける
    i = 0
    s = 0
    # 数量Xを満たすまで、板情報を取得する
    while s <= size_thru:
        if value['bids'][i]['price'] == rate_bid:
            s += float(value['bids'][i]['size']) - size_bid
        else:
            s += float(value['bids'][i]['size'])
        i += 1

    j = 0
    t = 0
    while t <= size_thru:
        if value['asks'][j]['price'] == rate_ask:
            t += float(value['asks'][j]['size']) - size_ask
        else:
            t += float(value['asks'][j]['size'])
        j += 1

    time.sleep(0.1)
    # 数量Xを満たす最良気配値を返す
    # さらに在庫リスクを考慮したオフセット値を含むような値にする
    return {'bid': float(value['bids'][i-1]['price'])+offset, 'ask': float(value['asks'][j-1]['price'])+offset}

# 約定履歴からビッドオファーのブレイクを確認する関数
def get_breaking(break_ask, break_bid):

    while True:
        try:
            value = bitflyer.public_get_getexecutions(params = {"product_code" : "FX_BTC_JPY", "count" : 30})
            break
        except Exception as e:
            logger.info(e)
            time.sleep(1)
    ask = 0
    bid = 0
    for i in range(len(value)):
        if break_ask < float(value[-i-1]['price']):   # 時間順に参照したいので逆順でforを回す
            bid = float(value[-i-1]['price'])
        if break_bid > float(value[-i-1]['price']):
            ask = float(value[-i-1]['price'])
    if ask != 0 and bid != 0:
        ask = 0
        bid = 0
    return {'ask': ask, 'bid': bid}

# 成行注文する関数
def market(side, size):

    while True:
        try:
            value = bitflyer.private_post_sendchildorder({"product_code":PAIR, "child_order_type":"MARKET", "side":side, "size":size})
            break
        except Exception as e:
            logger.info(e)
            time.sleep(2)

    time.sleep(0.1)
    return value

# 指値注文する関数
def limit(side, size, price):

    while True:
        try:
            value = bitflyer.private_post_sendchildorder({"product_code":PAIR, "child_order_type":"LIMIT", "side":side, "price":price, "size":size})
            break
        except Exception as e:
            logger.info(e)
            time.sleep(2)

    time.sleep(0.1)
    return value

# 注文をキャンセルする関数
def cancel(id):

    try:
        value = bitflyer.private_post_cancelchildorder({"product_code":PAIR, "child_order_acceptance_id":id})  # idは別途指定するはず
    except Exception as e:
        logger.info(e)
        logger.info('cannot cancel')

        # 指値が約定していた(=キャンセルが通らなかった)場合、
        # 注文情報を更新(約定済み)して返す
        value = get_status(id)

    time.sleep(0.1)
    return value

# 指定した注文idのステータスを参照する関数
def get_status(id):

    if PAIR == 'BTC/JPY':
        PRODUCT = 'BTC_JPY'
    else:
        PRODUCT = PAIR

    while True:
        try:
            value = bitflyer.private_get_getchildorders(params = {'product_code': PRODUCT, 'child_order_acceptance_id': id})[0]
            break
        except Exception as e:
            logger.info(e)
            time.sleep(2)

    # APIで受け取った値を読み換える
    if value['child_order_state'] == 'ACTIVE':
        status = 'open'
    elif value['child_order_state'] == 'COMPLETED':
        status = 'closed'
    else:
        status = value['child_order_state']

    # 未約定量を計算する
    remaining = float(value['size']) - float(value['executed_size'])

    return {'id': value['child_order_acceptance_id'], 'status': status, 'filled': value['executed_size'], 'remaining': remaining, 'amount': value['size'], 'price': value['price']}

#------------------------------------------------------------------------------#

# 未約定量が存在することを示すフラグ
remaining_ask_flag = 0
remaining_bid_flag = 0

# 指値の有無を示す変数
pos = 'none'

# 在庫の定期確認までのタイムフラグ
pos_i = 0

#------------------------------------------------------------------------------#

logger.info('--------TradeStart--------')
logger.info('BOT TYPE      : MarketMaker @ bitFlyer')
logger.info('SYMBOL        : {0}'.format(PAIR))
logger.info('LOT           : {0} {1}'.format(LOT, COIN))
logger.info('SPREAD ENTRY  : {0} %'.format(SPREAD_ENTRY * 100))
logger.info('SPREAD CANCEL : {0} %'.format(SPREAD_CANCEL * 100))

# 残高取得
asset = float(get_asset()['info'][0]['amount'])
colla = float(get_colla()['collateral'])
logger.info('--------------------------')
logger.info('ASSET         : {0}'.format(int(asset)))
logger.info('COLLATERAL    : {0}'.format(int(colla)))
logger.info('TOTAL         : {0}'.format(int(asset + colla)))

# メインループ
while True:

    # 未約定量の繰越がなければリセット
    if remaining_ask_flag == 0:
        remaining_ask = 0
    if remaining_bid_flag == 0:
        remaining_bid = 0

    # フラグリセット
    remaining_ask_flag = 0
    remaining_bid_flag = 0

    # 自分の指値が存在しないとき実行する
    if pos == 'none':

        # 板情報を取得、実効ask/bid(指値を入れる基準値)を決定する
        Amount = get_amount()
        #offset = get_offset(amount['offset'])
        tick = get_effective_tick(size_thru=Amount['X'], offset=0, rate_ask=0, size_ask=0, rate_bid=0, size_bid=0)
        ask = float(tick['ask'])
        bid = float(tick['bid'])
        # 実効スプレッドを計算する
        spread = (ask - bid) / bid

        time.sleep(1)
        # 基準となるビッドオファーがブレイクしたか確認する
        breaking = get_breaking(break_ask=ask, break_bid=bid)
        #logger.info('--------------------------')
        #logger.info('ask:{0}, bid:{1}, spread:{2}%, X:{3}, break_ask:{4}'.format(int(ask * 100) / 100, int(bid * 100) / 100, int(spread * 10000) / 100, Amount['X'], breaking['ask']))

        # 基準値をブレイクアウトした場合に実行する
        # 下方向に歩み値が動いた場合、askで売りを入れる
        if breaking['ask'] != 0:

            logger.info('--------------------------')
            logger.info('ask:{0}, bid:{1}, spread:{2}%, X:{3}'.format(int(ask * 100) / 100, int(bid * 100) / 100, int(spread * 10000) / 100, Amount['X']))
            logger.info('bid:{0}, break_ask:{1}, spread:{2}'.format(int(bid * 100) / 100, breaking['ask'], (int(bid * 100) / 100) - breaking['ask']))

            # 前回のサイクルにて未約定量が存在すれば今回の注文数に加える
            amount_int_ask = round(LOT + remaining_bid, 8)
            amount_int_bid = round(LOT + remaining_ask, 8)

            # 板情報を取得、最新ask/bid(指値を入れる基準値)を取得する
            Amount = get_amount()
            tick = get_effective_tick(size_thru=Amount['X'], offset=0, rate_ask=0, size_ask=0, rate_bid=0, size_bid=0)
            ask = float(tick['ask'])
            bid = float(tick['bid'])
            spread = (ask - bid) / bid
            logger.info('ask:{0}, bid:{1}, spread:{2}%, X:{3}'.format(int(ask * 100) / 100, int(bid * 100) / 100, int(spread * 10000) / 100, Amount['X']))
            logger.info('ask:{0}, break_ask:{1}, spread:{2}'.format(int(ask * 100) / 100, breaking['ask'], (int(ask * 100) / 100) - breaking['ask']))

            # 実効Ask/Bidからdelta離れた位置に指値を入れる
            trade_ask = limit('SELL', amount_int_ask, ask - DELTA)  # 逆に短期的な上げを見込む（逆選択リスク寄りの考え方？）
            trade_bid = limit('BUY', amount_int_bid, bid + DELTA)  # 短期的な下げを見込んで低めに買いを打っておく
            trade_ask = get_status(trade_ask['child_order_acceptance_id'])
            trade_bid = get_status(trade_bid['child_order_acceptance_id'])
            trade_ask['status'] = 'open'
            trade_bid['status'] = 'open'
            pos = 'entry'

            logger.info('--------------------------')
            logger.info('entry')

            time.sleep(1)

        # 上方向に歩み値が動いた場合、bidで買いを入れる
        if breaking['bid'] != 0:

            logger.info('--------------------------')
            logger.info('ask:{0}, bid:{1}, spread:{2}%, X:{3}'.format(int(ask * 100) / 100, int(bid * 100) / 100, int(spread * 10000) / 100, Amount['X']))
            logger.info('ask:{0}, break_bid:{1}, spread:{2}'.format(int(ask * 100) / 100, breaking['bid'], breaking['bid'] - (int(ask * 100) / 100)))

            # 前回のサイクルにて未約定量が存在すれば今回の注文数に加える
            amount_int_ask = round(LOT + remaining_bid, 8)
            amount_int_bid = round(LOT + remaining_ask, 8)

            # 板情報を取得、最新ask/bid(指値を入れる基準値)を取得する
            Amount = get_amount()
            tick = get_effective_tick(size_thru=Amount['X'], offset=0, rate_ask=0, size_ask=0, rate_bid=0, size_bid=0)
            ask = float(tick['ask'])
            bid = float(tick['bid'])
            spread = (ask - bid) / bid
            logger.info('ask:{0}, bid:{1}, spread:{2}%, X:{3}'.format(int(ask * 100) / 100, int(bid * 100) / 100, int(spread * 10000) / 100, Amount['X']))
            logger.info('bid:{0}, break_bid:{1}, spread:{2}'.format(int(bid * 100) / 100, breaking['bid'], (int(bid * 100) / 100) - breaking['bid']))

            # 実効Ask/Bidからdelta離れた位置に指値を入れる
            trade_ask = limit('SELL', amount_int_ask, ask - DELTA)  # 短期的な上げを見込んで高めに買いを打っておく
            trade_bid = limit('BUY', amount_int_bid, bid + DELTA)
            trade_ask = get_status(trade_ask['child_order_acceptance_id'])
            trade_bid = get_status(trade_bid['child_order_acceptance_id'])
            trade_ask['status'] = 'open'
            trade_bid['status'] = 'open'
            pos = 'entry'

            logger.info('--------------------------')
            logger.info('entry')

            time.sleep(1)

    # 自分の指値が存在するとき実行する
    if pos == 'entry':

        # 注文ステータス取得
        if trade_ask['status'] != 'closed':
            trade_ask = get_status(trade_ask['id'])
        if trade_bid['status'] != 'closed':
            trade_bid = get_status(trade_bid['id'])

        # 板情報を取得、実効Ask/Bid(指値を入れる基準値)を決定する
        Amount = get_amount()
        Offset = get_offset(Amount['offset'], trade_ask['status'], trade_bid['status'])
        tick = get_effective_tick(size_thru=Amount['X'], offset=Offset, rate_ask=float(trade_ask['price']), size_ask=float(trade_ask['amount']), rate_bid=float(trade_bid['price']), size_bid=float(trade_bid['amount']))
        ask = float(tick['ask'])
        bid = float(tick['bid'])
        spread = (ask - bid) / bid

        logger.info('--------------------------')
        logger.info('ask:{0}, bid:{1}, spread:{2}%, X:{3}, offset:{4}'.format(int(ask * 100) / 100, int(bid * 100) / 100, int(spread * 10000) / 100, Amount['X'], Offset))
        logger.info('ask status:{0}, filled:{1}/{2}, price:{3}'.format(trade_ask['status'], trade_ask['filled'], trade_ask['amount'], trade_ask['price']))
        logger.info('bid status:{0}, filled:{1}/{2}, price:{3}'.format(trade_bid['status'], trade_bid['filled'], trade_bid['amount'], trade_bid['price']))

        # Ask未約定量が最小注文量を下回るとき実行
        if trade_ask['status'] == 'open' and trade_ask['remaining'] < AMOUNT_MIN:

            # 注文をキャンセル
            cancel_ask = cancel(trade_ask['id'])

            # ステータスをCLOSEDに書き換える
            trade_ask['status'] = 'closed'

            # 未約定量を記録、次サイクルで未約定量を加えるフラグを立てる
            remaining_ask = float(trade_ask['remaining'])
            remaining_ask_flag = 1

            logger.info('--------------------------')
            logger.info('ask remaining has {}'.format(remaining_ask))
            logger.info('ask almost filled.')

        # Bid未約定量が最小注文量を下回るとき実行
        if trade_bid['status'] == 'open' and trade_bid['remaining'] < AMOUNT_MIN:

            # 注文をキャンセル
            cancel_bid = cancel(trade_bid['id'])

            # ステータスをCLOSEDに書き換える
            trade_bid['status'] = 'closed'

            # 未約定量を記録、次サイクルで未約定量を加えるフラグを立てる
            remaining_bid = float(trade_bid['remaining'])
            remaining_bid_flag = 1

            logger.info('--------------------------')
            logger.info('bid remaining has {}'.format(remaining_bid))
            logger.info('bid almost filled.')

        #スプレッドが閾値以上のときに実行する
        if spread > SPREAD_CANCEL:

            # Ask指値が最良位置に存在しないとき、指値を更新する
            if trade_ask['status'] == 'open' and trade_ask['price'] != ask - DELTA:

                # 時間差で約定していると、在庫が積み上がるから再度確認
                trade_ask = get_status(trade_ask['id'])
                if trade_ask['status'] == 'closed':
                    logger.info('ask time closed')

                if trade_ask['status'] == 'open':
                    # 指値を一旦キャンセル
                    cancel_ask = cancel(trade_ask['id'])

                    # 注文数が最小注文数より大きいとき、指値を更新する
                    if trade_ask['remaining'] >= AMOUNT_MIN:
                        trade_ask = limit('SELL', trade_ask['remaining'], ask - DELTA - 10)   # 逆選択リスク（在庫リスク）軽減のため、早めに切れるよう指値を狭めてみる
                        trade_ask = get_status(trade_ask['child_order_acceptance_id'])
                        trade_ask['status'] = 'open'
                    # 注文数が最小注文数より小さく0でないとき、未約定量を記録してCLOSEDとする
                    elif AMOUNT_MIN > trade_ask['remaining'] > 0:
                        trade_ask['status'] = 'closed'
                        remaining_ask = float(trade_ask['remaining'])
                        remaining_ask_flag = 1
                    # 注文数が最小注文数より小さく0のとき、CLOSEDとする
                    else:
                        trade_ask['status'] = 'closed'

            # Bid指値が最良位置に存在しないとき、指値を更新する
            if trade_bid['status'] == 'open' and trade_bid['price'] != bid + DELTA:

                trade_bid = get_status(trade_bid['id'])
                if trade_bid['status'] == 'closed':
                    logger.info('bid time closed')

                if trade_bid['status'] == 'open':
                    # 指値を一旦キャンセル
                    cancel_bid = cancel(trade_bid['id'])

                    # 注文数が最小注文数より大きいとき、指値を更新する
                    if trade_bid['remaining'] >= AMOUNT_MIN:
                        trade_bid = limit('BUY', trade_bid['remaining'], bid + DELTA + 10)   # 逆選択リスク（在庫リスク）軽減のため、早めに切れるよう指値を狭めてみる
                        trade_bid = get_status(trade_bid['child_order_acceptance_id'])
                        trade_bid['status'] = 'open'
                    # 注文数が最小注文数より小さく0でないとき、未約定量を記録してCLOSEDとする
                    elif AMOUNT_MIN > trade_bid['remaining'] > 0:
                        trade_bid['status'] = 'closed'
                        remaining_bid = float(trade_bid['remaining'])
                        remaining_bid_flag = 1
                    # 注文数が最小注文数より小さく0のとき、CLOSEDとする
                    else:
                        trade_bid['status'] = 'closed'

        # Ask/Bid両方の指値が約定したとき、1サイクル終了、最初の処理に戻る
        if trade_ask['status'] == 'closed' and trade_bid['status'] == 'closed':
            pos = 'none'

            logger.info('--------------------------')
            logger.info('completed.')

            pos_i += 1
            if pos_i > 4:
                po = get_position()
                if po['size'] >= 0.01:
                    logger.info('fund position {}, {}'.format(po['size'], po['side']))
                    trade_pos = market(po['side'], po['size'])
                    pos_i = 0
                    time.sleep(3)
    time.sleep(0.5)
