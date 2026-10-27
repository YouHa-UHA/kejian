# 独立部署

本地试用优先使用 README 中的演示命令。以下仅为自行部署的通用说明。

## 应用运行

创建独立系统用户、Python 虚拟环境和数据目录；安装生产 WSGI 依赖：

```sh
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.txt
```

运行时从私密环境文件读取以下参数，环境文件不提交到仓库：

```dotenv
KEJIAN_DB=/var/lib/kejian/classroom.sqlite3
KEJIAN_ORIGIN=https://class.example.com
KEJIAN_BASE=/mem/
KEJIAN_RELEASE=your-reviewed-release
```

`KEJIAN_ORIGIN` 是自己的准确 HTTPS 来源；`KEJIAN_BASE` 要以斜杠开头和结尾。需要额外来源时明确配置 `KEJIAN_EXTRA_ORIGINS`，不要开放任意来源。

```sh
.venv/bin/gunicorn --bind 127.0.0.1:18027 --workers 1 --threads 4 'classroom.app:production()'
```

以上命令需要先在进程环境设置参数。`deploy/kejian-classroom.service` 与 `deploy/kejian-classroom.nginx.conf` 是通用参考，路径、域名、证书与资源限制按自己的环境核对。

## 账号与数据

正式账号使用 `python3 -m classroom.cli --help` 按自己的名单开通。名单 CSV、初始密码文件和开通码输出属于私密材料。已有账号不会因再次开通而重置密码。

```sh
python3 -m classroom.cli --db /path/to/private.sqlite3 admin YOUR_STUDENT_NUMBER
python3 -m classroom.cli --db /path/to/private.sqlite3 backup --output /path/to/new-backup.sqlite3
```

上线前在独立副本验证，再备份自己的数据库并发布代码。恢复代码通常不需要覆盖数据库；不要用旧数据库覆盖上线后的新作业、评论或账号记录。

演示数据和演示密码用于本地开发，不导入正式数据库。

## 可选：iOS 消息提醒

当前仅支持 iOS（iPhone / iPad）。接收者需要使用有效 HTTPS 来源，在 Safari 中添加到主屏幕，再从桌面打开、登录并主动开启设备提醒。普通桌面网页或 Android 浏览器的通知能力不在本版本支持范围内。

Web 进程和通知 worker 使用同一个私密配置路径，通过 `KEJIAN_PUSH_CONFIG` 指向它。配置文件及 VAPID 私钥由部署者自行生成并保管，不放入仓库；包含以下字段：

| 字段 | 含义 |
| --- | --- |
| `environment` | 正式环境填 `production`，对应 `KEJIAN_BASE=/mem/` |
| `publicKey` | 自己生成的 VAPID 公钥，使用无填充的 Base64URL 编码 |
| `privateKeyPath` | 私密 PEM 文件的绝对路径，仅运行用户可读 |
| `subject` | 部署者自己的联系 URI，例如 `mailto:maintainer@example.com` |

示例配置只展示字段结构，不包含可运行的密钥：

```json
{
  "environment": "production",
  "publicKey": "REPLACE_WITH_YOUR_OWN_VAPID_PUBLIC_KEY",
  "privateKeyPath": "/etc/kejian/push-private.pem",
  "subject": "mailto:maintainer@example.com"
}
```

发送依赖单独安装到 worker 的虚拟环境。`deploy/requirements-push.txt` 固定了已验证的 Linux 发行包哈希；在其他操作系统上需要重新核对对应发行包，不要移除哈希校验来掩盖平台不匹配。

```sh
python3 -m venv /opt/kejian/push-venv
/opt/kejian/push-venv/bin/pip install --require-hashes -r deploy/requirements-push.txt
/opt/kejian/push-venv/bin/python -m classroom.push_worker
```

worker 也要加载 `KEJIAN_DB`、`KEJIAN_BASE`、`KEJIAN_PUSH_CONFIG`。当前安全校验要求正式数据库为 `/var/lib/kejian/classroom.sqlite3`；测试数据库位于 `/var/lib/kejian-test/` 且使用 `/mem-test/`。不要混用数据库、私钥、订阅、Cookie 或环境标识。

`deploy/kejian-push.service` 是独立进程参考，限制内存和 CPU。调度器按变更只重算受影响账号；空闲时仅做轻量检查，定期兜底补齐滚动窗口；发送并发上限为 5。发送前再次核对会话、设备归属、教学班和完成状态。不确定的网络结果不盲目重发；系统只保留短期投递状态，不保留不断增长的提醒列表。

没有开启该配置时，演示与网页功能照常运行，通知入口隐藏。部署者仍需在自己的 iOS 设备上验收锁屏、点击跳转、退出和换号隔离；仓库中的模拟测试不能替代真机验收。
