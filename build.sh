#!/bin/bash
# 股票分析系统镜像构建和部署脚本
# 用法: ./build.sh [tag]
# 如果不提供tag，则使用git最新的tag

set -e

# 定义变量
REPO_NAME="k8sf/stock-scanner"
VALUES_FILE="helm-chart/stock-scanner/values.yaml"
DEFAULT_TAG="latest"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# 显示帮助信息
function show_help {
    echo -e "${YELLOW}股票分析系统镜像构建和部署脚本${NC}"
    echo "用法: ./build.sh [tag]"
    echo "  如果不提供tag，则使用git最新的tag"
    echo ""
    echo "选项:"
    echo "  -h, --help    显示帮助信息"
    echo "  -p, --push    构建后推送镜像到仓库"
    echo "  -u, --update  更新Helm图表中的tag"
    echo ""
    echo "示例:"
    echo "  ./build.sh v1.0.0    # 构建v1.0.0版本的镜像"
    echo "  ./build.sh -p        # 构建最新tag版本的镜像并推送"
    echo "  ./build.sh -p -u     # 构建最新tag版本的镜像，推送并更新Helm图表"
}

# 解析命令行参数
PUSH=false
UPDATE=false
TAG=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        -p|--push)
            PUSH=true
            shift
            ;;
        -u|--update)
            UPDATE=true
            shift
            ;;
        *)
            if [[ -z $TAG ]]; then
                TAG=$1
            else
                echo -e "${RED}错误: 不能同时指定多个tag${NC}"
                show_help
                exit 1
            fi
            shift
            ;;
    esac
done

# 如果未指定tag，尝试使用git最新tag
if [[ -z $TAG ]]; then
    echo -e "${YELLOW}未指定tag，尝试获取git最新tag...${NC}"
    if command -v git &> /dev/null; then
        GIT_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
        if [[ -n $GIT_TAG ]]; then
            TAG=${GIT_TAG#v} # 移除前缀v (如果有)
            echo -e "${GREEN}使用最新git tag: ${TAG}${NC}"
        else
            echo -e "${YELLOW}未找到git tag，使用默认tag: ${DEFAULT_TAG}${NC}"
            TAG=$DEFAULT_TAG
        fi
    else
        echo -e "${YELLOW}git命令不可用，使用默认tag: ${DEFAULT_TAG}${NC}"
        TAG=$DEFAULT_TAG
    fi
fi

echo -e "${GREEN}开始构建镜像: ${REPO_NAME}:${TAG}${NC}"

# 构建Docker镜像
docker build -t "${REPO_NAME}:${TAG}" .

echo -e "${GREEN}镜像构建完成: ${REPO_NAME}:${TAG}${NC}"

# 如果指定了推送选项，则推送镜像
if $PUSH; then
    echo -e "${YELLOW}推送镜像到Docker仓库...${NC}"
    docker push "${REPO_NAME}:${TAG}"
    echo -e "${GREEN}镜像推送完成: ${REPO_NAME}:${TAG}${NC}"
fi

# 如果指定了更新选项，则更新Helm图表
if $UPDATE; then
    echo -e "${YELLOW}更新Helm图表中的tag值...${NC}"
    if [[ -f $VALUES_FILE ]]; then
        # 使用sed更新values.yaml中的tag
        if [[ "$OSTYPE" == "darwin"* ]]; then
            # macOS
            sed -i '' "s/^\(.*tag: \).*$/\1\"$TAG\"/" $VALUES_FILE
        else
            # Linux
            sed -i "s/^\(.*tag: \).*$/\1\"$TAG\"/" $VALUES_FILE
        fi
        echo -e "${GREEN}已更新Helm图表tag值为: ${TAG}${NC}"
        echo -e "${YELLOW}请检查 ${VALUES_FILE} 确认更新是否正确${NC}"
    else
        echo -e "${RED}错误: 找不到Helm values文件: ${VALUES_FILE}${NC}"
        exit 1
    fi
fi

echo -e "${GREEN}所有操作已完成${NC}"
echo "镜像: ${REPO_NAME}:${TAG}"
if $UPDATE; then
    echo "Helm图表已更新"
    echo "可以使用以下命令进行部署:"
    echo "  helm upgrade --install stock-scanner ./helm-chart/stock-scanner"
fi 