from fastapi import FastAPI, Request, Response, Depends, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Generator
from services.stock_analyzer_service import StockAnalyzerService
from services.us_stock_service_async import USStockServiceAsync
from services.fund_service_async import FundServiceAsync
from services.a_stock_list_service import AStockListService
import os
import httpx
from utils.logger import get_logger
from utils.api_utils import APIUtils
from dotenv import load_dotenv
import uvicorn
import json
import secrets
import traceback
from datetime import datetime, timedelta
from jose import JWTError, jwt

load_dotenv()

# 获取日志器
logger = get_logger()

# 日志级别
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
TRACE_ENABLED = LOG_LEVEL == "TRACE"

# JWT相关配置
SECRET_KEY = os.getenv("JWT_SECRET_KEY", secrets.token_hex(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 10080  # Token过期时间一周

LOGIN_PASSWORD = os.getenv("LOGIN_PASSWORD", "")
print(LOGIN_PASSWORD)

# 是否需要登录
REQUIRE_LOGIN = bool(LOGIN_PASSWORD.strip())

MODE = os.getenv("MODE", "RELEASE")

app = FastAPI(
    title="Stock Scanner API",
    description="异步股票分析API，支持A股、美股、港股及ETF基金的AI智能分析",
    version="1.0.0",
    docs_url="/docs" if MODE == "DEBUG" else None,
    redoc_url=None,
    openapi_url="/openapi.json" if MODE == "DEBUG" else None
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境允许所有来源，生产环境应该限制
    allow_credentials=True,
    allow_methods=["*"],    
    allow_headers=["*"],
)

# 初始化异步服务
us_stock_service = USStockServiceAsync()
fund_service = FundServiceAsync()
a_stock_list_service = AStockListService()

# 定义请求和响应模型
class AnalyzeRequest(BaseModel):
    stock_codes: List[str] = Field(..., description="股票代码列表", example=["600000"])
    market_type: str = Field("A", description="市场类型(A/US/HK/ETF/LOF)", example="A")
    api_url: Optional[str] = Field(None, description="自定义API URL", example="https://api.openai.com/v1")
    api_key: Optional[str] = Field(None, description="自定义API Key", example="sk-xxxxxx")
    api_model: Optional[str] = Field(None, description="自定义AI模型", example="gpt-4o")
    api_timeout: Optional[str] = Field(None, description="自定义API超时时间(秒)", example="60")

class TestAPIRequest(BaseModel):
    api_url: str = Field(..., description="API URL", example="https://api.openai.com/v1")
    api_key: str = Field(..., description="API Key", example="sk-xxxxxx")
    api_model: Optional[str] = Field(None, description="AI模型", example="gpt-4o")
    api_timeout: Optional[int] = Field(10, description="API超时时间(秒)", example=10)

class LoginRequest(BaseModel):
    password: str = Field(..., description="登录密码", example="your_password")

class Token(BaseModel):
    access_token: str = Field(..., description="访问令牌")
    token_type: str = Field(..., description="令牌类型", example="bearer")

class LoginResponse(BaseModel):
    access_token: str = Field(..., description="访问令牌")
    token_type: str = Field(..., description="令牌类型", example="bearer")

class AuthStatus(BaseModel):
    authenticated: bool = Field(..., description="是否已认证")
    username: str = Field(..., description="用户名", example="user")

class ConfigResponse(BaseModel):
    announcement: str = Field(..., description="系统公告", example="欢迎使用股票分析系统！这是测试环境。")
    default_api_url: str = Field(..., description="默认API URL", example="https://one-api.inner.ai.kingstartech.com")
    default_api_model: str = Field(..., description="默认API模型", example="gpt-4o")
    default_api_timeout: str = Field(..., description="默认API超时时间", example="60")

class NeedLoginResponse(BaseModel):
    require_login: bool = Field(..., description="是否需要登录")

class SearchResult(BaseModel):
    name: str = Field(..., description="股票/基金名称")
    symbol: str = Field(..., description="股票/基金代码")
    price: float = Field(..., description="当前价格")
    market_value: float = Field(..., description="市值")

class SearchResponse(BaseModel):
    results: List[SearchResult] = Field(..., description="搜索结果列表")

class AStockListItem(BaseModel):
    ts_code: str = Field(..., description="股票代码（带市场后缀，如000001.SZ）", example="000001.SZ")
    symbol: str = Field(..., description="股票代码（不带后缀）", example="000001")
    name: str = Field(..., description="股票名称", example="平安银行")
    area: Optional[str] = Field(None, description="地区", example="深圳")
    industry: Optional[str] = Field(None, description="行业", example="银行")
    market: Optional[str] = Field(None, description="市场（主板/创业板/科创板）", example="主板")
    list_date: Optional[str] = Field(None, description="上市日期", example="19910403")

class AStockListResponse(BaseModel):
    count: int = Field(..., description="股票数量")
    update_time: str = Field(..., description="数据更新时间")
    items: List[AStockListItem] = Field(..., description="股票列表")

class TestApiResponse(BaseModel):
    success: bool = Field(..., description="测试是否成功")
    message: str = Field(..., description="测试结果消息")
    status_code: Optional[int] = Field(None, description="HTTP状态码")

class ErrorResponse(BaseModel):
    detail: str = Field(..., description="错误详情")

# 自定义依赖项，在REQUIRE_LOGIN=False时不要求token
class OptionalOAuth2PasswordBearer(OAuth2PasswordBearer):
    async def __call__(self, request: Request) -> Optional[str]:
        if not REQUIRE_LOGIN:
            return None
        try:
            return await super().__call__(request)
        except HTTPException:
            if not REQUIRE_LOGIN:
                return None
            raise

# 使用自定义的依赖项
optional_oauth2_scheme = OptionalOAuth2PasswordBearer(tokenUrl="login")

# 创建访问令牌
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# 验证令牌
async def verify_token(token: Optional[str] = Depends(optional_oauth2_scheme)):
    if not REQUIRE_LOGIN:
        return "guest"
    if token is None:
        return "guest"
    if token != LOGIN_PASSWORD:
        raise HTTPException(status_code=401, detail="无效的TOKEN")
    return "user"

# 用户登录接口（简化为直接比对TOKEN）
@app.post("/api/login", response_model=LoginResponse, responses={
    200: {"description": "登录成功", "model": LoginResponse},
    401: {"description": "登录失败", "model": ErrorResponse}
})
async def login(request: LoginRequest):
    """
    用户登录接口
    
    直接比对TOKEN进行登录验证，成功后返回访问令牌
    
    - **password**: 登录密码
    
    返回:
    - **access_token**: 访问令牌
    - **token_type**: 令牌类型
    """
    if request.password != LOGIN_PASSWORD:
        logger.warning("登录失败：TOKEN错误")
        raise HTTPException(status_code=401, detail="TOKEN错误")
    logger.info("用户登录成功")
    return {"access_token": LOGIN_PASSWORD, "token_type": "bearer"}

# 检查用户认证状态
@app.get("/api/check_auth", response_model=AuthStatus, responses={
    200: {"description": "认证状态查询成功", "model": AuthStatus},
    401: {"description": "未授权", "model": ErrorResponse}
})
async def check_auth(username: str = Depends(verify_token)):
    """
    检查用户认证状态
    
    验证当前用户认证状态，返回是否认证及用户名
    
    返回:
    - **authenticated**: 是否已认证
    - **username**: 用户名
    """
    return {"authenticated": True, "username": username}

# 获取系统配置
@app.get("/api/config", response_model=ConfigResponse)
async def get_config():
    """
    获取系统配置信息
    
    返回系统公告和默认API配置信息
    
    返回:
    - **announcement**: 系统公告
    - **default_api_url**: 默认API URL
    - **default_api_model**: 默认API模型
    - **default_api_timeout**: 默认API超时时间
    """
    config = {
        'announcement': os.getenv('ANNOUNCEMENT_TEXT') or '',
        'default_api_url': os.getenv('API_URL', ''),
        'default_api_model': os.getenv('API_MODEL', ''),
        'default_api_timeout': os.getenv('API_TIMEOUT', '60')
    }
    return config

# AI分析股票
@app.post("/api/analyze", responses={
    200: {"description": "分析请求已接受，返回流式响应"},
    400: {"description": "请求参数错误", "model": ErrorResponse},
    401: {"description": "未授权", "model": ErrorResponse},
    500: {"description": "服务器内部错误", "model": ErrorResponse}
})
async def analyze(request: AnalyzeRequest, username: str = Depends(verify_token)):
    """
    AI分析股票
    
    对指定股票进行AI分析，支持单只或多只股票分析。返回流式JSON响应。
    
    - **stock_codes**: 股票代码列表
    - **market_type**: 市场类型，如A股、美股、港股、ETF等
    - **api_url**: 自定义API URL，可选
    - **api_key**: 自定义API Key，可选
    - **api_model**: 自定义API模型，可选
    - **api_timeout**: 自定义API超时时间，可选
    
    响应示例:
    ```
    {"stream_type": "single", "stock_code": "600000"}
    {"stock_code": "600000", "market_type": "A", "analysis_date": "2025-04-29", "score": 50, ...}
    {"stock_code": "600000", "status": "analyzing", "ai_analysis_chunk": "分析"}
    {"stock_code": "600000", "status": "completed", "ai_analysis": "完整分析结果", "score": 50}
    ```
    """
    try:
        logger.info("开始处理分析请求")
        stock_codes = request.stock_codes
        market_type = request.market_type
        
        # 后端再次去重，确保安全
        original_count = len(stock_codes)
        stock_codes = list(dict.fromkeys(stock_codes))  # 保持原有顺序的去重方法
        if len(stock_codes) < original_count:
            logger.info(f"后端去重: 从{original_count}个代码中移除了{original_count - len(stock_codes)}个重复项")
        
        logger.debug(f"接收到分析请求: stock_codes={stock_codes}, market_type={market_type}")
        
        # 获取自定义API配置
        custom_api_url = request.api_url
        custom_api_key = request.api_key
        custom_api_model = request.api_model
        custom_api_timeout = request.api_timeout
        
        logger.debug(f"自定义API配置: URL={custom_api_url}, 模型={custom_api_model}, API Key={'已提供' if custom_api_key else '未提供'}, Timeout={custom_api_timeout}")
        
        # 创建新的分析器实例，使用自定义配置
        custom_analyzer = StockAnalyzerService(
            custom_api_url=custom_api_url,
            custom_api_key=custom_api_key,
            custom_api_model=custom_api_model,
            custom_api_timeout=custom_api_timeout
        )
        
        if not stock_codes:
            logger.warning("未提供股票代码")
            raise HTTPException(status_code=400, detail="请输入代码")
        
        # 定义流式生成器
        async def generate_stream():
            if len(stock_codes) == 1:
                # 单个股票分析流式处理
                stock_code = stock_codes[0].strip()
                logger.info(f"开始单股流式分析: {stock_code}")
                
                stock_code_json = json.dumps(stock_code)
                init_message = f'{{"stream_type": "single", "stock_code": {stock_code_json}}}\n'
                yield init_message
                
                logger.debug(f"开始处理股票 {stock_code} 的流式响应")
                chunk_count = 0
                
                # 使用异步生成器
                async for chunk in custom_analyzer.analyze_stock(stock_code, market_type, stream=True):
                    chunk_count += 1
                    yield chunk + '\n'
                
                logger.info(f"股票 {stock_code} 流式分析完成，共发送 {chunk_count} 个块")
            else:
                # 批量分析流式处理
                logger.info(f"开始批量流式分析: {stock_codes}")
                
                stock_codes_json = json.dumps(stock_codes)
                init_message = f'{{"stream_type": "batch", "stock_codes": {stock_codes_json}}}\n'
                yield init_message
                
                logger.debug(f"开始处理批量股票的流式响应")
                chunk_count = 0
                
                # 使用异步生成器
                async for chunk in custom_analyzer.scan_stocks(
                    [code.strip() for code in stock_codes], 
                    min_score=0, 
                    market_type=market_type,
                    stream=True
                ):
                    chunk_count += 1
                    yield chunk + '\n'
                
                logger.info(f"批量流式分析完成，共发送 {chunk_count} 个块")
        
        logger.info("成功创建流式响应生成器")
        return StreamingResponse(generate_stream(), media_type='application/json')
            
    except Exception as e:
        error_msg = f"分析时出错: {str(e)}"
        logger.error(error_msg)
        if TRACE_ENABLED:
            trace_info = traceback.format_exc()
            logger.error(f"错误堆栈: \n{trace_info}")
        else:
            logger.exception(e)
        raise HTTPException(status_code=500, detail=error_msg)

# 搜索美股代码
@app.get("/api/search_us_stocks", response_model=SearchResponse, responses={
    200: {"description": "搜索成功", "model": SearchResponse},
    400: {"description": "请求参数错误", "model": ErrorResponse},
    401: {"description": "未授权", "model": ErrorResponse},
    500: {"description": "服务器内部错误", "model": ErrorResponse}
})
async def search_us_stocks(keyword: str = "", username: str = Depends(verify_token)):
    """
    搜索美股代码
    
    根据关键词搜索美股代码，返回匹配的股票列表
    
    - **keyword**: 搜索关键词，可以是公司名称或股票代码的一部分
    
    返回:
    - **results**: 匹配的股票列表，包含名称、代码、价格和市值
    
    示例响应:
    ```json
    {
      "results": [
        {
          "name": "Apple Hospitality REIT Inc",
          "symbol": "106.APLE",
          "price": 11.94,
          "market_value": 2851968424.0
        }
      ]
    }
    ```
    """
    try:
        if not keyword:
            raise HTTPException(status_code=400, detail="请输入搜索关键词")
        
        # 直接使用异步服务的异步方法
        results = await us_stock_service.search_us_stocks(keyword)
        return {"results": results}
        
    except Exception as e:
        logger.error(f"搜索美股代码时出错: {str(e)}")
        if TRACE_ENABLED:
            trace_info = traceback.format_exc()
            logger.error(f"错误堆栈: \n{trace_info}")
        else:
            logger.exception(e)
        raise HTTPException(status_code=500, detail=str(e))

# 搜索基金代码
@app.get("/api/search_funds", response_model=SearchResponse, responses={
    200: {"description": "搜索成功", "model": SearchResponse},
    400: {"description": "请求参数错误", "model": ErrorResponse},
    401: {"description": "未授权", "model": ErrorResponse},
    500: {"description": "服务器内部错误", "model": ErrorResponse}
})
async def search_funds(keyword: str = "", market_type: str = "", username: str = Depends(verify_token)):
    """
    搜索基金代码
    
    根据关键词搜索基金代码，返回匹配的基金列表
    
    - **keyword**: 搜索关键词，可以是基金名称或代码的一部分
    - **market_type**: 市场类型，如ETF、LOF等，可选
    
    返回:
    - **results**: 匹配的基金列表，包含名称、代码、价格和市值
    
    示例响应:
    ```json
    {
      "results": [
        {
          "name": "易方达创业板ETF",
          "symbol": "159915",
          "price": 3.256,
          "market_value": 26645000000.0
        }
      ]
    }
    ```
    """
    try:
        if not keyword:
            raise HTTPException(status_code=400, detail="请输入搜索关键词")
        
        # 直接使用异步服务的异步方法
        results = await fund_service.search_funds(keyword, market_type)
        return {"results": results}
        
    except Exception as e:
        logger.error(f"搜索基金代码时出错: {str(e)}")
        if TRACE_ENABLED:
            trace_info = traceback.format_exc()
            logger.error(f"错误堆栈: \n{trace_info}")
        else:
            logger.exception(e)
        raise HTTPException(status_code=500, detail=str(e))

# 获取美股详情
@app.get("/api/us_stock_detail/{symbol}", responses={
    200: {"description": "获取成功"},
    400: {"description": "请求参数错误", "model": ErrorResponse},
    401: {"description": "未授权", "model": ErrorResponse},
    500: {"description": "服务器内部错误", "model": ErrorResponse}
})
async def get_us_stock_detail(symbol: str, username: str = Depends(verify_token)):
    """
    获取美股详情
    
    根据股票代码获取美股详细信息
    
    - **symbol**: 美股股票代码
    
    返回详细的股票信息，包括:
    - 价格
    - 涨跌幅
    - 成交量
    - 市值
    - 市盈率
    - 股息率等
    
    示例响应:
    ```json
    {
      "code": "AAPL",
      "name": "Apple Inc.",
      "price": 210.14,
      "change": 0.86,
      "change_percent": 0.41,
      "volume": 38742989,
      "market_cap": "3.32T",
      "pe_ratio": 32.71,
      "dividend_yield": 0.53,
      "last_updated": "2025-04-28T16:00:00-04:00"
    }
    ```
    
    错误响应:
    ```json
    {
      "detail": "获取美股详情失败: 未找到股票代码: AAPL"
    }
    ```
    """
    try:
        if not symbol:
            raise HTTPException(status_code=400, detail="请提供股票代码")
        
        # 使用异步服务获取详情
        detail = await us_stock_service.get_us_stock_detail(symbol)
        return detail
        
    except Exception as e:
        logger.error(f"获取美股详情时出错: {str(e)}")
        if TRACE_ENABLED:
            trace_info = traceback.format_exc()
            logger.error(f"错误堆栈: \n{trace_info}")
        else:
            logger.exception(e)
        raise HTTPException(status_code=500, detail=str(e))

# 获取基金详情
@app.get("/api/fund_detail/{symbol}", responses={
    200: {"description": "获取成功"},
    400: {"description": "请求参数错误", "model": ErrorResponse},
    401: {"description": "未授权", "model": ErrorResponse},
    500: {"description": "服务器内部错误", "model": ErrorResponse}
})
async def get_fund_detail(symbol: str, market_type: str = "ETF", username: str = Depends(verify_token)):
    """
    获取基金详情
    
    根据基金代码获取基金详细信息
    
    - **symbol**: 基金代码
    - **market_type**: 市场类型，默认为ETF
    
    返回详细的基金信息，包括:
    - 价格
    - 涨跌幅
    - 成交量
    - 基金规模
    - 净值
    - 溢价/折价率等
    
    示例响应:
    ```json
    {
      "code": "159915",
      "name": "易方达创业板ETF",
      "price": 3.256,
      "change": 0.028,
      "change_percent": 0.87,
      "volume": 231450500,
      "fund_size": "266.45亿",
      "nav": 3.2543,
      "premium_discount": 0.05,
      "last_updated": "2025-04-29T15:00:00+08:00"
    }
    ```
    """
    try:
        if not symbol:
            raise HTTPException(status_code=400, detail="请提供基金代码")
        
        # 使用异步服务获取详情
        detail = await fund_service.get_fund_detail(symbol, market_type)
        return detail
        
    except Exception as e:
        logger.error(f"获取基金详情时出错: {str(e)}")
        if TRACE_ENABLED:
            trace_info = traceback.format_exc()
            logger.error(f"错误堆栈: \n{trace_info}")
        else:
            logger.exception(e)
        raise HTTPException(status_code=500, detail=str(e))

# 测试API连接
@app.post("/api/test_api_connection", response_model=TestApiResponse, responses={
    200: {"description": "测试成功", "model": TestApiResponse},
    400: {"description": "请求参数错误或连接失败", "model": TestApiResponse},
    401: {"description": "未授权", "model": ErrorResponse},
    500: {"description": "服务器内部错误", "model": TestApiResponse}
})
async def test_api_connection(request: TestAPIRequest, username: str = Depends(verify_token)):
    """
    测试API连接
    
    测试与第三方AI服务提供商的连接是否正常
    
    - **api_url**: API URL
    - **api_key**: API Key
    - **api_model**: AI模型，可选
    - **api_timeout**: API超时时间(秒)，可选
    
    成功响应:
    ```json
    {
      "success": true,
      "message": "API 连接测试成功"
    }
    ```
    
    失败响应:
    ```json
    {
      "success": false,
      "message": "API 连接测试失败: 无效的API密钥",
      "status_code": 401
    }
    ```
    """
    try:
        logger.info("开始测试API连接")
        api_url = request.api_url
        api_key = request.api_key
        api_model = request.api_model
        api_timeout = request.api_timeout
        
        logger.debug(f"测试API连接: URL={api_url}, 模型={api_model}, API Key={'已提供' if api_key else '未提供'}, Timeout={api_timeout}")
        
        if not api_url:
            logger.warning("未提供API URL")
            raise HTTPException(status_code=400, detail="请提供API URL")
            
        if not api_key:
            logger.warning("未提供API Key")
            raise HTTPException(status_code=400, detail="请提供API Key")
            
        # 构建API URL
        test_url = APIUtils.format_api_url(api_url)
        logger.debug(f"完整API测试URL: {test_url}")
        print(f"完整API测试URL: {test_url}")
        
        # 使用异步HTTP客户端发送测试请求
        async with httpx.AsyncClient(timeout=float(api_timeout)) as client:
            response = await client.post(
                test_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": api_model or "",
                    "messages": [
                        {"role": "user", "content": "Hello, this is a test message. Please respond with 'API connection successful'."}
                    ],
                    "max_tokens": 20
                }
            )
        
        # 检查响应
        if response.status_code == 200:
            logger.info(f"API 连接测试成功: {response.status_code}")
            return {"success": True, "message": "API 连接测试成功"}
        else:
            error_data = response.json()
            error_message = error_data.get('error', {}).get('message', '未知错误')
            logger.warning(f"API连接测试失败: {response.status_code} - {error_message}")
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": f"API 连接测试失败: {error_message}", "status_code": response.status_code}
            )
            
    except httpx.RequestError as e:
        logger.error(f"API 连接请求错误: {str(e)}")
        if TRACE_ENABLED:
            trace_info = traceback.format_exc()
            logger.error(f"错误堆栈: \n{trace_info}")
        else:
            logger.exception(e)  # 仅在非TRACE模式下使用exception
        
        response_content = {
            "success": False, 
            "message": f"请求错误: {str(e)}"
        }
        
        # 仅在TRACE模式下添加trace
        if TRACE_ENABLED:
            response_content["trace"] = traceback.format_exc()
            
        return JSONResponse(
            status_code=400,
            content=response_content
        )
    except Exception as e:
        logger.error(f"测试 API 连接时出错: {str(e)}")
        if TRACE_ENABLED:
            trace_info = traceback.format_exc()
            logger.error(f"错误堆栈: \n{trace_info}")
        else:
            logger.exception(e)
            
        response_content = {
            "success": False,
            "message": f"API 测试连接时出错: {str(e)}"
        }
        
        # 仅在TRACE模式下添加trace
        if TRACE_ENABLED:
            response_content["trace"] = traceback.format_exc()
            
        return JSONResponse(
            status_code=500,
            content=response_content
        )

# 检查是否需要登录
@app.get("/api/need_login", response_model=NeedLoginResponse)
async def need_login():
    """
    检查是否需要登录
    
    检查系统是否配置为需要登录认证
    
    返回:
    - **require_login**: 是否需要登录，true表示需要登录，false表示不需要登录
    
    示例响应:
    ```json
    {
      "require_login": false
    }
    ```
    """
    return {"require_login": REQUIRE_LOGIN}

# 获取A股股票列表
@app.get("/api/a_stock_list", response_model=AStockListResponse, responses={
    200: {"description": "获取成功", "model": AStockListResponse},
    401: {"description": "未授权", "model": ErrorResponse},
    500: {"description": "服务器内部错误", "model": ErrorResponse}
})
async def get_a_stock_list(force_refresh: bool = False, username: str = Depends(verify_token)):
    """
    获取A股股票列表
    
    返回全量A股股票列表，包含代码、名称、行业等基础信息。数据每日15点后更新一次。
    
    - **force_refresh**: 是否强制刷新缓存，默认为False
    
    返回:
    - **count**: 股票数量
    - **update_time**: 数据更新时间
    - **items**: 股票列表
    
    示例响应:
    ```json
    {
      "count": 5000,
      "update_time": "2025-04-29 15:30:00",
      "items": [
        {
          "ts_code": "000001.SZ",
          "symbol": "000001",
          "name": "平安银行",
          "area": "深圳",
          "industry": "银行",
          "market": "主板",
          "list_date": "19910403"
        },
        {
          "ts_code": "000002.SZ",
          "symbol": "000002",
          "name": "万科A",
          "area": "深圳",
          "industry": "房地产",
          "market": "主板",
          "list_date": "19910129"
        }
      ]
    }
    ```
    """
    try:
        logger.info(f"开始获取A股股票列表, force_refresh={force_refresh}")
        
        # 从服务获取股票列表
        stock_list_df = await a_stock_list_service.get_stock_list(force_refresh=force_refresh)
        
        # 转换为响应格式
        stock_list = stock_list_df.to_dict(orient='records')
        
        # 获取更新时间
        cache_file = a_stock_list_service.cache_file
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                    update_time = cache_data.get('update_time', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            except Exception as e:
                logger.error(f"读取缓存文件更新时间出错: {str(e)}")
                update_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        else:
            update_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 构建响应
        response = {
            "count": len(stock_list),
            "update_time": update_time,
            "items": stock_list
        }
        
        logger.info(f"A股股票列表获取成功，共{len(stock_list)}条记录")
        return response
    
    except Exception as e:
        error_msg = f"获取A股股票列表时出错: {str(e)}"
        logger.error(error_msg)
        if TRACE_ENABLED:
            trace_info = traceback.format_exc()
            logger.error(f"错误堆栈: \n{trace_info}")
        else:
            logger.exception(e)
        raise HTTPException(status_code=500, detail=error_msg)

# 设置静态文件
frontend_dist = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'frontend', 'dist')
if os.path.exists(frontend_dist):
    # 直接挂载整个dist目录
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="static")
    logger.info(f"前端构建目录挂载成功: {frontend_dist}")
else:
    logger.warning("前端构建目录不存在，仅API功能可用")


if __name__ == '__main__':
    uvicorn.run("web_server:app", host="0.0.0.0", port=8888, reload=True)