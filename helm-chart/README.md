# 股票分析系统 Helm Chart

## 概述

此Helm Chart用于在Kubernetes集群中部署股票分析系统。

## 前提条件

- Kubernetes 1.16+
- Helm 3.0+
- PV供应器支持持久卷声明（如果启用持久化）

## 安装

```bash
# 添加仓库
# helm repo add k8sf https://your-helm-repo-url

# 更新仓库
# helm repo update

# 安装Chart
helm install stock-scanner ./stock-scanner
```

## 配置

| 参数 | 描述 | 默认值 |
|------|---------|-------|
| `image.repository` | 镜像仓库 | `k8sf/stock-scanner` |
| `image.tag` | 镜像标签 | `latest` |
| `image.pullPolicy` | 镜像拉取策略 | `IfNotPresent` |
| `service.type` | Kubernetes服务类型 | `ClusterIP` |
| `service.port` | 服务端口 | `8888` |
| `ingress.enabled` | 是否启用Ingress | `true` |
| `ingress.className` | Ingress类名 | `nginx` |
| `env` | 环境变量列表 | 见values.yaml |
| `persistence.enabled` | 是否启用持久化存储 | `true` |
| `persistence.size` | 持久卷大小 | `5Gi` |

## 环境变量配置说明

| 环境变量 | 描述 | 默认值 |
|---------|------|-------|
| `API_KEY` | AI服务API密钥 | - |
| `API_URL` | AI服务API地址 | - |
| `API_MODEL` | AI服务使用的模型 | `gpt-4` |
| `API_TIMEOUT` | API请求超时时间(秒) | `60` |
| `TOKEN` | API认证令牌(替代LOGIN_PASSWORD) | - |
| `ANNOUNCEMENT_TEXT` | 公告文本内容 | `欢迎使用股票分析系统` |
| `MODE` | 应用模式(RELEASE/DEBUG) | `RELEASE` |
| `LOG_LEVEL` | 日志级别(INFO/TRACE等) | `INFO` |
| `USER_TOKEN` | 连接外部AI服务的Token | - |

## 自定义配置

创建自定义values.yaml文件:

```bash
cat > my-values.yaml << EOL
env:
  - name: API_KEY
    value: "你的API密钥"
  - name: API_URL
    value: "你的API地址"
  - name: API_MODEL
    value: "gpt-4"
  - name: API_TIMEOUT
    value: "60"
  - name: TOKEN
    value: "你的API认证令牌"
  - name: MODE
    value: "RELEASE"
  - name: LOG_LEVEL
    value: "INFO"
  - name: ANNOUNCEMENT_TEXT
    value: "欢迎使用股票分析系统"

ingress:
  hosts:
    - host: stocks.example.com
      paths:
        - path: /
          pathType: ImplementationSpecific
EOL

helm install stock-scanner ./stock-scanner -f my-values.yaml
```

## 卸载

```bash
helm uninstall stock-scanner
```

## 注意事项

- 股票分析仅供参考，不构成投资建议
- 请确保API配置正确
- MODE设为DEBUG可启用API文档(Swagger UI)
- LOG_LEVEL设为TRACE可查看详细堆栈跟踪 