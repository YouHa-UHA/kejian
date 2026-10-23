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

演示数据和演示密码用于本地开发，不导入正式数据库。班级版未包含旧个人版通知后台；手机推送需要后续单独配置与验收。
