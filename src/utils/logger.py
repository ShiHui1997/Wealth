"""
结构化日志模块
记录系统运行状态，生成运行摘要，支持健康检查告警
"""
import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional


class RunLogger:
    """
    运行日志记录器
    记录每次运行的步骤、耗时、状态和关键指标
    """

    def __init__(self, log_dir: str = "logs"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        self.steps: List[Dict] = []
        self.start_time = datetime.now()
        self.current_step: Optional[Dict] = None

    def step_start(self, name: str, detail: str = "") -> str:
        """开始记录一个步骤"""
        step_id = f"step_{len(self.steps) + 1}"
        self.current_step = {
            "id": step_id,
            "name": name,
            "detail": detail,
            "start": datetime.now().isoformat(),
            "status": "running",
        }
        self.steps.append(self.current_step)
        print(f"[{step_id}] {name} - {detail}")
        return step_id

    def step_end(self, step_id: str = None, status: str = "ok",
                 result: str = "", error: str = ""):
        """结束当前步骤"""
        if step_id:
            step = next((s for s in self.steps if s["id"] == step_id), None)
        else:
            step = self.current_step

        if step:
            step["end"] = datetime.now().isoformat()
            step["status"] = status
            step["result"] = result
            step["error"] = error
            start_dt = datetime.fromisoformat(step["start"])
            end_dt = datetime.fromisoformat(step["end"])
            step["duration_sec"] = (end_dt - start_dt).total_seconds()
            icon = {"ok": "✅", "warning": "⚠️", "error": "❌"}.get(status, "?")
            print(f"[{step['id']}] {icon} {step['name']} - {result} "
                  f"({step['duration_sec']:.1f}s)")

        self.current_step = None

    def record_metric(self, name: str, value, unit: str = ""):
        """记录一个关键指标"""
        metric = {
            "name": name,
            "value": value,
            "unit": unit,
            "timestamp": datetime.now().isoformat(),
        }
        if self.current_step:
            self.current_step.setdefault("metrics", []).append(metric)
        else:
            self.steps.append({"type": "metric", **metric})
        print(f"  📊 {name}: {value}{unit}")

    def summary(self) -> Dict:
        """生成运行摘要"""
        end_time = datetime.now()
        duration = (end_time - self.start_time).total_seconds()

        ok_count = sum(1 for s in self.steps if s.get("status") == "ok")
        warn_count = sum(1 for s in self.steps if s.get("status") == "warning")
        err_count = sum(1 for s in self.steps if s.get("status") == "error")

        return {
            "start_time": self.start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_sec": round(duration, 1),
            "total_steps": len(self.steps),
            "ok_count": ok_count,
            "warning_count": warn_count,
            "error_count": err_count,
            "overall_status": "error" if err_count > 0 else (
                "warning" if warn_count > 0 else "ok"
            ),
            "steps": self.steps,
        }

    def save(self, filename: str = None) -> str:
        """保存日志到文件"""
        if filename is None:
            filename = f"run_{self.start_time.strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(self.log_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.summary(), f, ensure_ascii=False, indent=2)
        return filepath

    def print_summary(self):
        """打印运行摘要"""
        s = self.summary()
        print(f"\n{'='*50}")
        print(f"  运行摘要")
        print(f"{'='*50}")
        print(f"  开始: {s['start_time']}")
        print(f"  结束: {s['end_time']}")
        print(f"  耗时: {s['duration_sec']:.1f}秒")
        print(f"  步骤: {s['total_steps']} "
              f"(✅{s['ok_count']} ⚠️{s['warning_count']} ❌{s['error_count']})")
        print(f"  状态: {s['overall_status']}")
        print(f"{'='*50}")


class HealthChecker:
    """
    系统健康检查器
    在运行失败时发送告警通知
    """

    def __init__(self, notifier=None):
        self.notifier = notifier

    def alert_on_error(self, error: Exception, context: str = ""):
        """运行出错时发送告警"""
        error_msg = f"{type(error).__name__}: {str(error)}"
        print(f"[健康检查] ❌ 系统异常: {error_msg}")
        print(f"[健康检查] 上下文: {context}")

        if self.notifier:
            alert_content = f"""
            <div style="font-family:sans-serif;padding:16px;">
                <h2 style="color:#e74c3c;">❌ 大乐透预测系统异常</h2>
                <p><b>错误类型:</b> {type(error).__name__}</p>
                <p><b>错误信息:</b> {str(error)[:500]}</p>
                <p><b>发生时间:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                <p><b>上下文:</b> {context}</p>
                <hr>
                <p style="color:#888;font-size:12px;">
                    请检查 GitHub Actions 运行日志：<br>
                    https://github.com/ShiHui1997/Wealth/actions
                </p>
            </div>
            """
            try:
                self.notifier.send(
                    "❌ 大乐透系统异常告警",
                    alert_content,
                    content_type="html"
                )
                print("[健康检查] 告警已推送到微信")
            except Exception as e:
                print(f"[健康检查] 告警推送失败: {e}")

    def alert_on_warning(self, warning: str, context: str = ""):
        """发送警告通知"""
        print(f"[健康检查] ⚠️ {warning}")

        if self.notifier:
            alert_content = f"""
            <div style="font-family:sans-serif;padding:16px;">
                <h2 style="color:#f39c12;">⚠️ 大乐透预测系统警告</h2>
                <p><b>警告:</b> {warning}</p>
                <p><b>发生时间:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                <p><b>上下文:</b> {context}</p>
            </div>
            """
            try:
                self.notifier.send(
                    "⚠️ 大乐透系统警告",
                    alert_content,
                    content_type="html"
                )
            except Exception:
                pass
