# 本机自动启动与异常退出恢复

Windows 启动时，Cloudflared 服务负责公网隧道；当前用户登录后，注册表启动项 FloralScrollAtlas 静默运行 web/autostart.py，启动并守护 127.0.0.1:8976 上的网站。

守护程序每 5 秒检查一次网站进程。进程退出后，它调用现有 manage.py start --public 恢复网站，并确认健康接口响应。启动失败会持续重试，间隔为 5、10、20、40、60 秒，之后保持 60 秒。它监测的是进程退出，不会因为一次请求缓慢就强行终止仍在运行的进程。

重复登录启动或手动启动不会产生多个守护程序，Windows 文件锁保证只有一个实例。手动运行 manage.py start 或双击项目根目录的“启动网站.vbs”也会带起守护。既有网站进程可直接接管，无需先重启。

## 手动停止和恢复

在项目根目录执行：

- 停止：python web/manage.py stop
- 恢复：python web/manage.py start --public
- 状态：python web/manage.py status

stop 先设置 web/.runtime/server.stopped 暂停标记，再停止已核对身份的网站进程。守护程序继续待命，不会立即将网站拉起。暂停标记在重新登录后仍有效；执行 start 或双击启动入口会解除暂停并恢复网站。

## 状态与日志

- web/.runtime/watchdog.json：守护 PID、当前网站 PID、地址和状态。
- web/.runtime/autostart.log：进程退出码、重启尝试、健康检查结果和暂停记录。
- web/.runtime/server.json：网站 PID 和地址。
- web/.runtime/server.log：网站输出和错误。
- web/.runtime/watchdog-launch.log：守护启动失败时的错误输出。

当前登录启动项仍位于 HKCU\Software\Microsoft\Windows\CurrentVersion\Run 的 FloralScrollAtlas 值；无需打开 Codex 或浏览器。网站在登录后启动，守护退出后可通过再次运行启动入口恢复。

电脑需保持开机、联网且不休眠。此守护负责网站进程异常退出后的恢复，不能修复断网、关机或 Cloudflare 外部故障。网站原有队列会将未完成的运行中任务标记为中断，需要重新提交；已保存数据保持在原位置。
