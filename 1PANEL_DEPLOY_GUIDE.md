# 1Panel 部署与配置详细指南

本系统采用 **单容器极简架构**（FastAPI + SQLite + 本地持久化相册存储 + 本地轻量 AI OCR & 条码引擎），所有前端静态依赖与模型均已完全内置，极度契合 1Panel 面板的容器化管理理念。

本指南提供两种启用 HTTPS 的方式（**推荐使用 Cloudflare Tunnel / cloudflared** 或 **1Panel OpenResty 反向代理 + SSL**），确保 **Passkey (指纹 / 面容 / 安全密钥免密登录)** 完美生效，并详解如何利用 **AI 图像智能识别资产 ID**。

---

## 一、为什么 Passkey 需要通过 HTTPS 访问？

根据 W3C WebAuthn 与各大浏览器（Chrome、Safari、Edge、Firefox 等）的强制安全标准：
> **Passkey 生物识别 API 仅允许在「安全上下文 (Secure Context)」中调用**。
> 即：只能在 `localhost`、`127.0.0.1` 或 **有效的 `https://` 域名** 下运行。
> 如果通过未加密的局域网 IP（如 `http://192.168.1.100:8000`）访问，浏览器会由于安全限制直接禁用生物识别弹窗。

借助 **Cloudflare Tunnel (cloudflared)** 或 **1Panel OpenResty 申请免费证书**，几分钟内即可搭建好原生支持 Passkey 的完整 HTTPS 资产管理平台。

---

## 二、部署方案 A：使用 Cloudflare Tunnel (cloudflared) 实现 HTTPS【推荐】

如果您没有公网 IP、不想在路由器映射端口、或者服务器没有 80/443 端口权限，使用 **Cloudflare Tunnel (cloudflared)** 是最安全、最优雅的 HTTPS 实现方式！

### 优势：
- 零端口开放：无需在防火墙或路由器开放任何进站端口。
- 自动 HTTPS 证书：Cloudflare 全球边缘节点自动颁发合规 SSL 证书。
- 手机与外网秒级访问：即使服务器在公司内网或家庭宽带中，手机在任何地方均可通过 `https://assets.yourdomain.com` 使用指纹/Face ID 免密登录。

### 部署步骤：

#### 1. 将项目文件放置于 1Panel
1. 打开 1Panel 控制面板，点击左侧菜单 **「主机」** -> **「文件」**。
2. 进入目录 `/opt/1panel/apps/`，新建文件夹 `asset-register`。
3. 将本项目的所有文件（包含 `app/`、`Dockerfile`、`docker-compose.yml`、`requirements.txt` 等）上传或解压到该目录。

#### 2. 在 1Panel 中启动 Docker Compose 编排
1. 打开 1Panel 左侧菜单 **「容器」** -> **「编排」**。
2. 点击右上角 **「创建编排」**：
   - **名称**：`asset-register`
   - **路径**：选择 `/opt/1panel/apps/asset-register/docker-compose.yml`。
3. 点击 **「确认」** 启动容器（服务会在本地监听 `8000` 端口）。

#### 3. 配置 Cloudflare Tunnel (二选一)

##### 方式 1：在 1Panel 应用商店安装官方 Cloudflared
1. 在 1Panel **「应用商店」** 中搜索并安装 `Cloudflared`。
2. 在 Cloudflare Zero Trust 控制台 (`one.dash.cloudflare.com`) -> **Networks** -> **Tunnels** 中新建一个 Tunnel，获取 `Token`。
3. 在 1Panel Cloudflared 中填入该 Token 启动。
4. 在 Cloudflare 控制台该 Tunnel 的 **Public Hostname** 中添加路由：
   - **Subdomain**：`assets` (例如 `assets.yourdomain.com`)
   - **Type**：`HTTP`
   - **URL**：`127.0.0.1:8000` (或 Docker 内网容器名 `asset-register:8000`)
5. 保存即可！Cloudflare 会自动完成全球解析与 HTTPS 证书签发。

##### 方式 2：直接在 `docker-compose.yml` 中共存运行 cloudflared
在项目的 `docker-compose.yml` 文件中，取消末尾 `cloudflared` 服务的注释，并填入您的 `TUNNEL_TOKEN`：
```yaml
  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: asset-cloudflared
    restart: unless-stopped
    command: tunnel --no-autoupdate run
    environment:
      - TUNNEL_TOKEN=你的Cloudflare_Tunnel_Token
    depends_on:
      - asset-register
```
保存并重新在 1Panel 中启动编排即可。

---

## 三、部署方案 B：使用 1Panel 网站反代 + Let's Encrypt 证书

如果您拥有公网独立 IP 并已做好域名解析：

1. 在 1Panel **「网站」** 中点击 **「创建网站」**，类型选择 **「反向代理」**。
2. **主域名** 填写您的域名（例如 `assets.yourcompany.com`），**代理地址** 填写 `http://127.0.0.1:8000`。
3. 进入该网站的 **「HTTPS」** 页面，勾选 **「启用 HTTPS」** 与 **「强制 HTTPS」**。
4. 一键申请免费的 **Let's Encrypt** SSL 证书并保存生效。

---

## 四、首位管理员 Passkey 初始化

1. 在电脑或手机浏览器中打开您的 HTTPS 地址（例如 `https://assets.yourcompany.com`）。
2. 首次访问系统会自动显示 **「系统首次初始化」** 界面：
   - 输入管理员账号（如 `admin`）。
   - 输入当前设备名称（如 `我的 iPhone 15` 或 `管理工作站`）。
   - 点击 **「生成 Passkey 并激活系统」** 按钮。
3. 浏览器会弹起系统原生安全窗口（如 iOS Face ID / Touch ID、Android 指纹、Windows Hello 或 YubiKey）。
4. 验证通过后即可立即进入管理后台，首位管理员 Passkey 绑定成功！

---

## 五、核心亮点：根据图片自动识别资产 ID (AI OCR & 条码)

系统内置了轻量自包含的高精度 OCR 与条码识别引擎（基于 ONNX Runtime 与 ZXing-CPP），无需依赖大型外部云服务：

### 1. 现场拍摄或上传照片自动取号
- 在 **「新建资产」** 弹窗中，点击 **「手机拍照」** 或选择设备相册上传照片（如设备铭牌、阀门管道标签、外壳序列号）。
- 系统后台会自动进行智能分析：
  1. **识别实物印刷标签**：即使文字垂直旋转、有反光塑料袋包裹（如示例中的工业阀门标签 `PU.023` / `Line 2 ONLY`），引擎也能精准识别并优先提取最符合资产规范的编号（`PU.023`）。
  2. **识别一维条码 / 二维码**：如果拍摄的是 Code 128、QR 码，系统会秒级解析条码内容。
- 识别完成后，系统会自动填充 **资产编号 (Asset ID)**，并列出候选标签供一键切换选择。

### 2. 扫码/图片寻物定位资产
- 点击顶部导航栏的 **「扫码寻物」**：
  - 支持调用摄像头实时扫描实物标签二维码/条码。
  - 支持点击 **「从相册选图识别」**，上传之前拍摄的设备照片，系统将自动识别图片中的编号并在数据库中秒级定位并打开该资产！

---

## 六、多设备绑定与数据备份

### 1. 绑定备用 Passkey 设备
为防止单台设备丢失导致失联：
1. 登录管理员账号后，点击右上角昵称进入凭据管理。
2. 点击「绑定当前设备」，可在手机、平板、备用笔记本上分别授权 Passkey。

### 2. 数据备份与恢复
所有数据均存储在持久化目录 `./data` 中：
- `data/assets.db`：资产信息与 Passkey 公钥凭据（SQLite 数据库）
- `data/uploads/`：全部资产高清原图与自动生成的快速缩略图
- `data/.secret_key`：会话签名密钥

**备份方案**：在 1Panel 的 **「计划任务」** 中添加定期备份任务，备份 `/opt/1panel/apps/asset-register/data` 目录即可实现全系统一键无损迁移与还原！
