# Cloudflare 临时公网测试

2026-09-20 已通过 Cloudflare Quick Tunnel 接通当前网站。

当前地址：<https://voting-deadline-showing-nutritional.trycloudflare.com>

访问链为：读者的浏览器 → Cloudflare HTTPS → 本机 cloudflared → `127.0.0.1:8976`。网页、Python生成器、编辑版本和自愿提交数据仍在本机。无需启动Docker或购买服务器。本次没有注册账户、购买域名、设置开机自启或修改路由器端口。

## 已检查

- 公网首页、原型目录、六幅分类图及图集原图可读取。
- 经公网提交的SW2-A指定数量请求完成，得到7条普通父枝、3条子枝，并下载了实际生成的PNG。
- 公网生成结果可以载入编辑器；编辑会话响应禁止公共缓存，HTTPS编辑身份Cookie带有Secure属性。
- 单个地址的生成请求限制为每分钟6次、每小时30次；编辑等写入限制为每分钟60次、每小时300次。地址仅在内存中用于运行限流，不进入研究反馈数据。
- 编辑保存仍需用户另行勾选并提交后才进入研究反馈目录。本次公网测试未提交研究反馈。

## 运行与停止

在项目根目录运行：

```bash
python web/manage.py start --public --inkscape D:/inkspace/bin/inkscape.exe
python web/tunnel.py start
python web/tunnel.py status
```

停止公网入口，保留本机网站：

```bash
python web/tunnel.py stop
```

停止本机网站：

```bash
python web/manage.py stop
```

管理脚本只处理本网站记录的隧道进程，并在停止前核对进程的可执行文件。运行文件、PID、日志和当前地址位于 `web/.runtime/cloudflare/`，已被Git忽略。cloudflared来自Cloudflare官方GitHub发布，当前安装版本为2026.9.1。更换机器时，从[官方下载页](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/)取得Windows程序，放到上述目录或用 `--cloudflared` 指定路径。

本机需要开机联网，网站与隧道进程需要保持运行。重新建立Quick Tunnel通常会更换随机地址。临时域名对应独立的浏览器会话，编辑结果应及时下载保留。

## 下一步

用手机关闭Wi-Fi后访问临时地址，检查实际目标网络的速度。需要论文长期链接时，再配置Cloudflare账户、固定域名和正式Tunnel。[Cloudflare将Quick Tunnel定位为开发与测试用途，不提供在线时间保证。](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)
