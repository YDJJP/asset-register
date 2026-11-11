# Asset Register (网页版资产登记与图片管理系统)

一个轻量、现代、安全的网页版资产管理系统，专为团队与个人设备/物资登记设计。支持 **Passkey (FIDO2 / WebAuthn 生物识别免密登录)**、**资产 ID 自动生成/扫码**、**多图与手机拍照上传**、**存放位置 (Location) 标签与快速筛选**、**二维码标签一键打印**，并针对 **1Panel** 面板进行了全方位的容器化部署优化。

---

## ✨ 核心特性

- 🔑 **Passkey 免密认证 (WebAuthn)**：
  - 支持设备原生生物识别（Touch ID、Face ID、Windows Hello、Android 指纹）及 YubiKey 物理安全密钥。
  - 支持多设备凭据绑定（电脑与手机均可作为独立 Passkey 凭据）。
  - 首次部署引导初始化，无需复杂的密码重置机制。
  - 完美适配 **Cloudflare Tunnel (cloudflared)** 边缘自动 HTTPS，实现免公网 IP、免端口映射、全设备生物识别。
- 🤖 **AI 图像自动识别资产 ID (OCR & 扫码识别)**：
  - 手机拍摄或上传设备照片，系统自动识别设备铭牌、印刷标签（如实物管道阀门上的 `PU.023`、`Line 2 ONLY`）或一维/二维码条码。
  - 智能过滤与打分排序，优先提取最符合资产规范的编号自动填充，并提供候选标签一键切换。
  - 扫描寻物支持直接上传照片定位已有资产。
- 📦 **资产 ID 与规格管理**：
  - 自定义输入或一键自动生成规范资产编号（如 `AST-261112-8821`）。
  - 支持条形码/现有资产标签号录入。
  - 资产类别分类（电子数码、办公家具、仪器设备、工具耗材等）与在用/闲置/维修状态流转。
- 📍 **存放位置 (Location) 深度管理**：
  - 突出显示存放地点（如 `A区仓库-02货架`、`研发部301工位`）。
  - 支持按地点一键聚合筛选与资产统计，快速掌握各位置资产分布。
  - 表单输入自带常用位置快捷选择，减少重复打字。
- 📸 **照片对应与多图管理**：
  - 单资产支持关联多张高清照片（整体照、铭牌/序列号特写、配件等）。
  - 手机端支持 **调起相机直接拍照上传** (`capture="environment"`)。
  - 支持从剪贴板直接粘贴图片 (`Ctrl+V` 截图直接入库)。
  - 自动 EXIF 方向修正（避免手机拍摄倒转）、自动生成轻量缩略图提速、支持大图全屏查看与设置主封面图。
- 🏷️ **资产二维码与标签打印**：
  - 内置热敏标签打印模版，一键生成包含资产 ID、名称、存放位置和二维码的标签。
  - 兼容各类便携热敏蓝牙打印机（50x30mm、60x40mm）或标准 A4 纸打印。
- 🔍 **摄像头扫码寻物 (QR/Barcode Scanner)**：
  - 支持直接调用手机或电脑摄像头扫描资产标签，秒级识别并自动定位该资产详情。
- 🚀 **1Panel 极简部署**：
  - 单容器轻量架构（FastAPI + SQLite + 本地持久化文件存储），内存占用仅 ~40MB。
  - 完美适配 1Panel 的 Docker Compose 编排与 OpenResty 反向代理 + 一键 Let's Encrypt SSL。
  - 所有前端静态库（Vue 3、Tailwind、SimpleWebAuthn、QRCode、Lucide）**全部内置本地化**，无外部 CDN 依赖，在局域网/纯内网离线环境亦可秒级加载。

---

## 🛠️ 技术栈

- **后端**：Python 3.12 + FastAPI + Uvicorn + Py-WebAuthn + Pillow + PyJWT
- **前端**：Vue 3 (ESM/Global) + Tailwind CSS + SimpleWebAuthn Browser + QRCode.js + Html5-QRCode + Lucide Icons
- **数据库**：SQLite (WAL 模式高并发优化)
- **部署形式**：Docker / Docker Compose（推荐运行于 1Panel）

---

## 🚀 本地快速开发与体验

### 1. 环境准备
确保已安装 Python 3.10+：
```bash
# 1. 克隆或进入项目目录
cd "asset register"

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动服务
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

打开浏览器访问 `http://127.0.0.1:8000`：
1. 首次打开会自动弹出「系统首次初始化」，输入用户名并轻触电脑指纹/Windows Hello/密码即可完成首位管理员 Passkey 注册。
2. 体验资产录入、图片上传、标签打印与扫码功能。

---

## 🐳 1Panel 部署指南 (推荐)

详细图文与避坑手册请查阅 👉 [**1PANEL_DEPLOY_GUIDE.md (1Panel 详细部署手册)**](./1PANEL_DEPLOY_GUIDE.md)。

### 极简部署三步法：

1. **上传目录**：
   将本项目代码上传至服务器的 `/opt/1panel/apps/asset-register`。
2. **在 1Panel 中启动编排**：
   进入 1Panel -> **容器** -> **编排** -> **创建编排**，选择项目目录中的 `docker-compose.yml`，点击「启动并构建」。
3. **配置反向代理与 SSL (Passkey 必需)**：
   在 1Panel -> **网站** -> 创建反向代理，代理地址指向 `127.0.0.1:8000`，并在证书管理中为您的域名申请免费 Let's Encrypt 证书并启用 HTTPS。

> ⚠️ **关于 Passkey 的重要安全规范**：
> 浏览器 W3C WebAuthn 规范严格要求 **Passkey 必须在 HTTPS 环境或 localhost 下才能调用**。在 1Panel 中通过反向代理配置域名和 SSL 证书后，即可在手机和电脑端畅享指纹/面容免密登录！

---

## 📂 项目结构

```text
├── app/
│   ├── config.py              # 配置读取 (RP_ID, ORIGIN, 数据目录)
│   ├── database.py            # SQLite 连接、WAL 模式与表结构初始化
│   ├── auth.py                # WebAuthn 挑战生成、校验与 JWT 会话
│   ├── models.py              # Pydantic 请求模型与校验
│   ├── main.py                # FastAPI 入口与静态资源挂载
│   ├── routers/
│   │   ├── auth_router.py     # 登录/注册挑战与会话 API
│   │   ├── user_router.py     # Passkey 凭据增删重命名
│   │   └── asset_router.py    # 资产增删改查、图片上传处理、统计、导出
│   └── static/
│       ├── index.html         # 单页面管理系统界面
│       ├── css/app.css        # 自定义动画与打印专用样式
│       ├── js/app.js          # Vue 3 核心业务交互逻辑
│       ├── js/webauthn.js     # WebAuthn 前端交互客户端封装
│       └── vendor/            # 100% 本地化前端库，支持纯离线内网
├── data/                      # 容器持久化数据卷目录
│   ├── assets.db              # SQLite 数据库文件
│   └── uploads/               # 高清原图与缩略图存放位置
├── Dockerfile                 # 轻量容器构建镜像定义
├── docker-compose.yml         # 1Panel 生产编排文件
├── requirements.txt           # Python 依赖清单
├── .env.example               # 环境变量参考
└── 1PANEL_DEPLOY_GUIDE.md     # 1Panel 专享部署文档
```

---

## 📄 许可协议

MIT License

