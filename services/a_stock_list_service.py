import os
import json
import datetime
import pandas as pd
import tushare as ts
from utils.logger import get_logger
from dotenv import load_dotenv

# 获取日志器
logger = get_logger()

# 加载环境变量
load_dotenv()

class AStockListService:
    """
    A股股票列表服务
    
    负责获取A股全量股票列表，并提供缓存机制，避免频繁调用tushare API
    在每天15点前如果有缓存数据，则直接使用缓存，15点后重新获取最新数据
    """
    
    def __init__(self):
        """初始化A股股票列表服务"""
        # Tushare API Token
        self.tushare_token = os.getenv('TUSHARE_TOKEN', '')
        
        # 如果没有设置TUSHARE_TOKEN，则在日志中警告
        if not self.tushare_token:
            logger.warning("未设置TUSHARE_TOKEN环境变量，将使用默认token")
            
        # 缓存文件路径
        self.cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'cache')
        self.cache_file = os.path.join(self.cache_dir, 'a_stock_list.json')
        
        # 确保缓存目录存在
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # 初始化tushare API
        ts.set_token(self.tushare_token)
        self.pro = ts.pro_api()
        
        logger.info("初始化AStockListService完成")
        
    async def get_stock_list(self, force_refresh=False):
        """
        获取A股股票列表
        
        Args:
            force_refresh: 是否强制刷新缓存，默认为False
            
        Returns:
            pandas.DataFrame: 包含A股股票列表的DataFrame
        """
        try:
            # 检查是否需要刷新缓存
            if force_refresh or self._should_refresh_cache():
                logger.info("开始从Tushare获取A股股票列表")
                
                # 调用tushare接口获取A股股票列表
                stock_list = self.pro.stock_basic(exchange='', list_status='L', 
                                            fields='ts_code,symbol,name,area,industry,market,list_date')
                
                # 仅保留A股
                stock_list = stock_list[stock_list['ts_code'].str.endswith(('SH', 'SZ'))]
                
                # 保存到缓存
                self._save_to_cache(stock_list)
                
                logger.info(f"成功获取A股股票列表，共{len(stock_list)}条记录")
                return stock_list
            else:
                # 从缓存加载
                logger.info("从缓存加载A股股票列表")
                stock_list = self._load_from_cache()
                logger.info(f"成功从缓存加载A股股票列表，共{len(stock_list)}条记录")
                return stock_list
                
        except Exception as e:
            logger.error(f"获取A股股票列表时出错: {str(e)}")
            logger.exception(e)
            
            # 如果出错且缓存存在，则尝试从缓存加载
            if os.path.exists(self.cache_file):
                logger.info("尝试从缓存加载A股股票列表")
                return self._load_from_cache()
            else:
                # 如果缓存也不存在，则返回空DataFrame
                logger.warning("无法获取A股股票列表，返回空DataFrame")
                return pd.DataFrame(columns=['ts_code', 'symbol', 'name', 'area', 'industry', 'market', 'list_date'])
    
    def _should_refresh_cache(self):
        """
        判断是否应该刷新缓存
        
        规则:
        1. 如果缓存文件不存在，则需要刷新
        2. 如果当前时间在15:00之后，且缓存是今天15:00之前的，则需要刷新
        3. 如果缓存日期不是今天，则需要刷新
        
        Returns:
            bool: 是否需要刷新缓存
        """
        # 如果缓存文件不存在，则需要刷新
        if not os.path.exists(self.cache_file):
            logger.info("缓存文件不存在，需要刷新")
            return True
            
        try:
            # 获取缓存文件的修改时间
            cache_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(self.cache_file))
            current_time = datetime.datetime.now()
            
            # 判断是否是同一天
            same_day = (cache_mtime.date() == current_time.date())
            
            # 今天15点的时间
            today_15 = current_time.replace(hour=15, minute=0, second=0, microsecond=0)
            
            # 如果今天15点前已经更新过缓存，且当前也是15点前，则不需要刷新
            if same_day and cache_mtime < today_15 and current_time < today_15:
                logger.info(f"今天已经更新过缓存，且当前时间在15点前，不需要刷新。缓存时间: {cache_mtime}")
                return False
                
            # 如果今天15点后更新过缓存，则不需要刷新
            if same_day and cache_mtime >= today_15:
                logger.info(f"今天15点后已经更新过缓存，不需要刷新。缓存时间: {cache_mtime}")
                return False
                
            # 其他情况需要刷新缓存
            logger.info(f"需要刷新缓存。缓存时间: {cache_mtime}, 当前时间: {current_time}")
            return True
            
        except Exception as e:
            logger.error(f"检查缓存刷新时出错: {str(e)}")
            # 出错时保守处理，返回需要刷新
            return True
    
    def _save_to_cache(self, stock_list):
        """
        保存股票列表到缓存文件
        
        Args:
            stock_list: pandas.DataFrame 股票列表
        """
        try:
            # 将DataFrame转换为JSON
            cache_data = {
                'update_time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'data': json.loads(stock_list.to_json(orient='records'))
            }
            
            # 写入JSON文件
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
                
            logger.info(f"股票列表已保存到缓存: {self.cache_file}")
            
        except Exception as e:
            logger.error(f"保存股票列表到缓存时出错: {str(e)}")
            logger.exception(e)
    
    def _load_from_cache(self):
        """
        从缓存文件加载股票列表
        
        Returns:
            pandas.DataFrame: 股票列表
        """
        try:
            # 读取JSON文件
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
                
            # 转换为DataFrame
            stock_list = pd.DataFrame(cache_data['data'])
            
            logger.info(f"从缓存加载股票列表成功，更新时间: {cache_data['update_time']}")
            
            return stock_list
            
        except Exception as e:
            logger.error(f"从缓存加载股票列表时出错: {str(e)}")
            logger.exception(e)
            # 出错时返回空DataFrame
            return pd.DataFrame(columns=['ts_code', 'symbol', 'name', 'area', 'industry', 'market', 'list_date']) 