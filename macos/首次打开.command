#!/bin/bash
# 桌面小猫 —— 首次打开助手（双击运行）
# 苹果对「从网上下载、又没有签名证书的 app」会拦一道，报「无法验证开发者」。
# 这个脚本做两件事：清掉下载标记（quarantine）、给 app 做一次本地临时签名，然后启动。
# 它不动你的任何文件，只处理这一个 app。

cd "$(dirname "$0")" || exit 1
echo "桌面小猫 · 首次打开"
echo "----------------------------------------"

APP=""
for p in "$(pwd)/桌面小猫.app" "/Applications/桌面小猫.app" "$HOME/Applications/桌面小猫.app"; do
  if [ -d "$p" ]; then APP="$p"; break; fi
done

if [ -z "$APP" ]; then
  echo "✗ 没找到「桌面小猫.app」。"
  echo "  请把这个脚本和 app 放在同一个文件夹里，或者先把 app 拖进「应用程序」，再双击本脚本。"
  echo
  read -n 1 -s -r -p "按任意键关闭…"
  exit 1
fi
echo "找到：$APP"

# 0) 常见故障：解压后启动器丢了执行权限，双击只会说「无法打开」
EXE="$APP/Contents/MacOS/deskcat"
if [ -x "$EXE" ]; then
  echo "✓ 启动器有执行权限"
else
  if chmod +x "$EXE" 2>/dev/null; then
    echo "✓ 启动器丢了执行权限，已补上（这就是「无法打开」的常见原因）"
  else
    echo "✗ 补执行权限失败：$EXE"
  fi
fi

if xattr -cr "$APP" 2>/dev/null; then
  echo "✓ 已清除「从网上下载」标记"
else
  echo "· 下载标记本来就没有（或已清除）"
fi

if command -v codesign >/dev/null 2>&1; then
  if codesign --force --deep --sign - "$APP" 2>/dev/null; then
    echo "✓ 已做本地临时签名"
  else
    echo "· 本地签名跳过（一般不影响使用）"
  fi
fi

echo "-------------------- 诊断信息 -------------------"
echo "系统: $(sw_vers -productVersion 2>/dev/null)  芯片: $(uname -m)"
if command -v spctl >/dev/null 2>&1; then
  spctl --assess --type execute -vv "$APP" 2>&1 | head -3 | sed 's/^/  /'
fi
if command -v codesign >/dev/null 2>&1; then
  codesign -dv "$APP" 2>&1 | grep -E "Signature|Identifier|flags" | head -3 | sed 's/^/  /'
fi
echo "-------------------------------------------------------------------------"
echo "正在启动…"
if open "$APP"; then
  echo "✓ 已启动。首次会先弹「正在准备运行环境」，约一分钟，需要联网。"
else
  echo "✗ 启动失败。请到「系统设置 → 隐私与安全性」，拉到底点「仍要打开」。"
fi
echo
echo "如果系统还弹窗：系统设置 → 隐私与安全性 → 拉到底 → 仍要打开。"
read -n 1 -s -r -p "按任意键关闭这个窗口…"
