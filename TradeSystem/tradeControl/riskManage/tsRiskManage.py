# encoding: UTF-8

from TradeSystem.tradeSystemBase.tsMssql import MSSQL
from TradeSystem.tradeControl.operateManage.tsOperateManage import OperateManage
from TradeSystem.tradeControl.HedgeManage.tsHedgeEngine import HedgeEngine
from TradeSystem.tradeSystemBase.tsFunction import *
import numpy as np


class RiskEngine:
    def __init__(self, _position_engine, _account):
        # 是否启动风控
        self.active = True
        # 风控的引擎
        self.position_engine = _position_engine
        # 账户内容
        self.account = _account
        # 数据库连接MSSQL
        self.sql_conn = MSSQL(host='127.0.0.1', user='sa', pwd='windows-999', db='stocks')
        alpha_max_position = self.account.list_fundvalue[-1][1] * self.account.capital_base * self.position_engine.alpha_position_ratio
        # 减去停牌的个股后进行对冲
        self.hedge_engine = HedgeEngine(self.account, alpha_max_position, self.position_engine.alpha_change_stock_flag)

    def buy(self, _buy_list):
        """买入"""
        dic_buy_result = {}

        buy_price = self.sql_conn.get_open_price(self.account.current_date, _buy_list)
        buy_price = buy_price.set_index('stockcode')
        buy_price = buy_price[buy_price['h'] != buy_price['l']]
        # buy_price = buy_price[buy_price['o'] != buy_price['l']]
        dic_buy_price = buy_price.to_dict()

        fundvalue = self.account.list_fundvalue[-1][1] * self.account.capital_base
        timing_rest_ratio = self.position_engine.break_position_ratio * 0.95 - self.account.list_fundvalue[-1][3]
        rest_position = fundvalue * timing_rest_ratio

        for stk in buy_price.index.values:
            referencenum = int(
                self.position_engine.dic_risk_ratio[stk] * self.account.capital_base * self.account.list_fundvalue[-1][1] * self.position_engine.break_position_ratio / _buy_list[stk]['risk'])

            if self.active and referencenum != 0:
                referencenum = self.buy_check(referencenum, dic_buy_price['open'][stk], rest_position)

                rest_position -= referencenum * dic_buy_price['open'][stk]

                OperateManage().order_to(self.account, stk, referencenum, dic_buy_price['open'][stk])
                dic_buy_result[stk] = referencenum

        return dic_buy_result

    def sell(self, _sell_list):
        """卖出"""
        dic_sell_result = {}

        # if self.account.current_date > datetime.datetime.strptime('2014-09-01', "%Y-%m-%d"):
        #     pass
        sell_price = self.sql_conn.get_open_price(self.account.current_date, _sell_list)
        sell_price = sell_price.set_index('stockcode')
        sell_price = sell_price[sell_price['h'] != sell_price['l']]
        dic_sell_price = sell_price.to_dict()

        for stk in sell_price.index.values:
            referencenum = 0

            if self.active and referencenum != 0:
                referencenum = self.sell_check(stk, 0)

            OperateManage().order_to(self.account, stk, referencenum, dic_sell_price['open'][stk])
            dic_sell_result[stk] = referencenum

        return dic_sell_result

    def sell_check(self, stk, referencenum):
        """卖出控制"""
        # todo 这里增加逻辑
        return 0

    def buy_check(self, referencenum, price, rest_cash):
        """买入控制"""
        cash_use = referencenum * price

        if self.account.cash >= cash_use and rest_cash >= cash_use:
            buy_referencenum = referencenum
        else:
            buy_referencenum = min(int(rest_cash / price), int(self.account.cash / price))
        return buy_referencenum

    def switch_Engine_Status(self):
        """控制风控引擎开关"""
        self.active = not self.active

    def operate(self):
        """整体仓位控制"""
        # 择时部分的买卖操作
        if len(self.account.sell_list):
            sell_result = self.sell(self.account.sell_list)
            for s in sell_result:
                if sell_result[s] == 0:
                    self.account.dic_high_stk_position.pop(s)

        if self.account.list_fundvalue:
            zig_fundvalue = self.account.list_fundvalue[-1][1]
        else:
            zig_fundvalue = 1

        require_zig_fundvalue = zig_fundvalue * self.account.capital_base * self.position_engine.break_position_ratio

        real_zig_fundvalue = 0

        for item in self.account.list_position:
            real_zig_fundvalue += self.account.list_position[item]['referencenum'] * self.account.list_position[item]['new_price']

        if real_zig_fundvalue > require_zig_fundvalue * 0.95:
            print('zig持仓超过标准的0.95，等比例减少')

            sell_price = self.sql_conn.get_open_price(self.account.current_date, self.account.list_position)

            sell_price = sell_price.set_index('stockcode')
            sell_price = sell_price[sell_price['h'] != sell_price['l']]
            dic_sell_price = sell_price.to_dict()

            for s in sell_price.index.values:
                referencenum = self.account.list_position[s]['referencenum'] * 0.95   # 非停牌股票等比例减少5%
                OperateManage().order_to(self.account, s, referencenum, dic_sell_price['open'][s])

        elif len(self.account.buy_list):
            buy_result = self.buy(self.account.buy_list)
            for s in buy_result:
                if s not in self.account.dic_high_stk_position.keys():
                    self.account.dic_high_stk_position[s] = dict(high_price=0, buy_date=self.account.current_date)

        if self.account.current_date > get_format_date(self.position_engine.alpha_start_date):
            # 获取alpha部分最新的模型建议持仓列表 alpha_buy_list 和 实际持仓列表
            alpha_buy_list = self.position_engine.alpha_buy_list
            alpha_position_list = self.position_engine.alpha_position_list
            # 获取当天开盘可买卖股票的的开盘价
            if len(alpha_buy_list) != 0:
                operate_price = self.sql_conn.get_open_price(self.account.current_date, set(alpha_buy_list).union(set(alpha_position_list.keys())))
                operate_price = operate_price.set_index('stockcode')
                operate_price = operate_price.dropna(how='any')
                operate_price = operate_price[operate_price['h'] != operate_price['l']]
                # operate_price = operate_price[operate_price['o'] != operate_price['l']]
                # 当天开盘时更新 alpha需卖出 但由于停牌无法卖出的 股票的列表
                alpha_to_sell_list = [s for s in alpha_position_list if s not in alpha_buy_list]  # 早晨不在buy_list内的持仓
                self.position_engine.alpha_stop_list = [s for s in alpha_to_sell_list if s not in list(operate_price.index)]
            else:
                operate_price = []

            # debug 输出alpha 各个部位头寸信息
            alpha_stock_value = self.position_engine.get_alpha_fundvalue()
            alpha_stop_value = self.position_engine.get_alpha_stop_fundvalue()
            # print 'alpha all stock: ' + str(alpha_stock_value) + ' //stopped: ' + str(alpha_stop_value) + ' //hedged: ' + str(alpha_stock_value-alpha_stop_value) \
            #  + ' //cash: ' + str(self.account.cash) + ' //deposit: ' + str(self.account.hedge_deposit)
            # if len(self.position_engine.alpha_stop_list) > 0:
            #     print self.position_engine.alpha_stop_list
            # 确定期货对冲的头寸
            [hedge_position_new, future_position_change] = self.hedge_engine.est_hedge_position(alpha_stop_value)
            # alpha 股票买操作
            self.alpha_buy_stock(hedge_position_new, operate_price, self.position_engine.alpha_change_stock_flag, future_position_change)
            # alpha 期货卖操作
            self.hedge_engine.open_hedge_trade(hedge_position_new, len(self.position_engine.alpha_position_list))

    def future_close_settlement(self):
        self.hedge_engine.future_close_settlement()

    def alpha_buy_stock(self, hedge_position_new, operate_price, alpha_change_stock_flag, future_position_change):
        # hedge_position_new是手数
        """alpha买卖"""
        buy_list = self.position_engine.alpha_buy_list
        position_list = self.position_engine.alpha_position_list

        if len(buy_list) != 0:
            dic_operate_price = operate_price.to_dict()

            operate_dic = {}
            operate_buy_list = []
            tmp_stop_list = []  # 选入 alpha buy_list 内后 临时停牌的股票
            tmp_stop_list_value = 0
            for s in buy_list:
                if s in operate_price.index.values.tolist():
                    operate_buy_list.append(s)
                elif s in position_list:    # 在alpha的buy_list 且在停牌状态 同时在 持仓列表
                    tmp_stop_list.append(s)
                    tmp_stop_list_value += self.position_engine.alpha_position_list[s]['referencenum'] * \
                                           self.position_engine.alpha_position_list[s]['new_price']  # 计算该list所占权益

            # @test@ 根据波动大小配权
            # atr_to_r_dic = {}
            # list_atr_keys = set(self.account.dic_ATR.keys())
            # for s in operate_buy_list:
            #     if s in list_atr_keys:
            #         atr_to_r_dic[s] = self.account.dic_ATR[s]['ATR'] * 10.0 / dic_operate_price['open'][s]
            #
            # max_atr_r = np.max(atr_to_r_dic.values())
            # min_atr_r = np.min(atr_to_r_dic.values())
            # atr_r_weight_dic = {}
            # sum_atr_r_weight = 0.0
            # for s in operate_buy_list:
            #     if s in atr_to_r_dic.keys():
            #         # atr_r_weight_dic[s] = max_atr_r + min_atr_r - atr_to_r_dic[s]
            #         atr_r_weight_dic[s] = atr_to_r_dic[s]
            #     else:
            #         atr_r_weight_dic[s] = min_atr_r
            #     sum_atr_r_weight += atr_r_weight_dic[s]
            #
            # stock_cash = hedge_position_new * self.account.hedge_position[1] * 300 - tmp_stop_list_value
            # for s in operate_buy_list:
            #     referencenum = stock_cash * atr_r_weight_dic[s] / sum_atr_r_weight / dic_operate_price['open'][s]
            #     one_hand_money = dic_operate_price['o'][s] * 100.0
            #     referencenum = round(referencenum / one_hand_money) * one_hand_money
            #     operate_dic[s] = referencenum

            # 等仓位配股
            stock_cash = (hedge_position_new * self.account.hedge_position[1] * 300 - tmp_stop_list_value) / len(operate_buy_list)
            for s in operate_buy_list:
                referencenum = stock_cash / dic_operate_price['open'][s]
                operate_dic[s] = referencenum

            for s in position_list.keys():
                if s in operate_price.index.values.tolist() and s not in operate_dic.keys():
                    operate_dic[s] = 0

            for s in operate_dic.keys():
                OperateManage().alpha_order_to(self.account, self.position_engine, s, operate_dic[s], dic_operate_price['open'][s])

        self.position_engine.alpha_stop_list = [s for s in position_list if s not in buy_list]

        if self.account.cash < 0:
            print self.position_engine.get_alpha_fundvalue()
            print('alpha调仓导致cash不足')
