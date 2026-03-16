# PyInstaller Build Helper

## 项目简介
这是一个专用于构建 PyInstaller 包的仓库，核心脚本为 `build.py`，
通过读取 `pyinstaller_config.json` 生成并执行 PyInstaller 命令。

仓库只维护构建逻辑与配置，不包含被打包应用本身的源码。

## 使用说明

### 运行构建
```bash
python build.py
```

### 仅打印命令（不执行）
```bash
python build.py --dry-run
```

### 清理构建缓存
```bash
python build.py --clean
```

### 指定 spec 输出目录
```bash
python build.py --specpath <dir>
```

### 配置说明（`pyinstaller_config.json`）
- `entry`: 入口脚本的绝对路径
- `name`: 输出名称
- `onefile`: `true/false`，单文件或目录模式
- `console`: `true/false`，是否显示控制台窗口
- `icon`: 图标路径或 `null`
- `add_data`: 额外数据文件映射列表
- `hidden_imports`: 隐式导入列表
- `excludes`: 排除模块列表
- `collect_binaries`: 需要收集二进制的模块列表
- `extra_args`: 额外的 PyInstaller 原始参数

### 示例
```json
{
  "entry": "C:\\path\\to\\app.py",
  "name": "app",
  "onefile": false,
  "console": true,
  "icon": null,
  "add_data": [],
  "hidden_imports": ["numpy"],
  "excludes": [],
  "collect_binaries": ["torch"],
  "extra_args": ["--collect-data=ultralytics"]
}
```
