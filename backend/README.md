
# 后端运行说明

## 环境要求

- Python 3.14
- MySQL 8.0 或兼容版本
- Node.js 18 及以上（需要重新构建前端时使用）

## 配置环境变量

在项目根目录的 `.env` 或系统环境变量中设置：

```text
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=你的 MySQL 密码
MYSQL_DATABASE=ai_chat
INVITE_CODE=邀请码（可选，设置后开放注册）
WEB_USER=外层门禁用户名（可选，Basic Auth）
WEB_PASSWORD=外层门禁密码（可选）
```

模型 API Key 在前端「模型配置」中按供应商填写，也可以勾选从环境变量读取（自行指定变量名）。

## 启动方式

在项目根目录运行 `快速启动.bat`。该脚本直接启动后端并打开浏览器，不会重新构建前端。

首次运行、依赖变化或前端源码变化后，运行 `重置启动.bat`。该脚本会安装后端依赖、构建前端并启动服务。

首次打开页面会要求创建管理员账号（仅限本机完成），旧版单一用户的数据会自动归入该账号。服务默认只监听 `127.0.0.1:8000`；如需公网访问，建议使用项目根目录的 `公网隧道.bat`，并可通过 `WEB_USER` / `WEB_PASSWORD` 叠加 Basic Auth 外层门禁。

## 开发构建

```text
cd frontend
npm install
npm run dev
```

生产构建使用：

```text
npm run build
```
