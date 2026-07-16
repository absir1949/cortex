# 听风官网

这是听风的独立静态官网目录，和产品 App 分开部署。

## 文件

- `MARKETING.md`：官网文案源文件
- `index.html`：官网页面
- `styles.css`：页面样式
- `script.js`：轻量交互和早期试用表单

## 本地预览

直接打开 `index.html` 即可，也可以在项目根目录启动静态服务：

```bash
python3 -m http.server 4173
```

然后访问：

```text
http://localhost:4173/website/
```

## 留资说明

当前表单采用纯静态方案：提交后生成一封申请邮件。

上线前如需更换收件地址，修改 `index.html` 中表单的 `data-lead-email`：

```html
<form class="trial-form" id="trialForm" data-lead-email="hello@aitingfeng.cn">
```
