
### 🐳 Docker 部署 

Docker 提供了环境一致性，是生产环境部署的首选方案。

#### 1.构建 Docker 镜像
```bash
使用 Docker 部署 (推荐)
# 1. 克隆仓库
git clone https://github.com/MGdaasLab/WHartTest.git
cd WHartTest

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，设置必要的环境变量

# 3. 启动服务（自动拉取预构建镜像）
docker-compose up -d
```
#### 2.访问平台地址
地址：http://localhost:8913/
#### 3.登录平台默认账号密码
username：admin

password：admin123456

