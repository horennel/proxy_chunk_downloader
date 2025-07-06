import os
import threading
import time
import argparse
import requests
import urllib3
from urllib.parse import urlparse
from rich.progress import Progress, BarColumn, TimeRemainingColumn, DownloadColumn, TransferSpeedColumn
from bark_python import BarkClient, CBCStrategy

client = BarkClient(device_key=os.getenv('BARK_DEVICE_KEY'), api_url=os.getenv('BARK_URL'))
client.set_encryption(
    key=os.getenv('BARK_KEY'),
    iv=os.getenv('BARK_IV'),
    strategy_cls=CBCStrategy
)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class Downloader:
    def __init__(self, url, output, num_threads, use_proxy, proxies, max_retries=3, retry_wait=1.0, verify_ssl=True):
        self.url = url
        self.output = output
        self.num_threads = num_threads
        self.use_proxy = use_proxy
        self.verify_ssl = verify_ssl
        self.proxies = proxies
        self.max_retries = max_retries
        self.retry_wait = retry_wait
        self.temp_files = [f"{output}.part{i}" for i in range(num_threads)]

    def get_file_size(self):
        try:
            headers = requests.head(self.url, verify=self.verify_ssl, timeout=(30, 30)).headers
            return int(headers.get('Content-Length', 0))
        except Exception as e:
            raise Exception(f"无法获取文件大小: {e}")

    def download_range_with_rich(self, start, end, part_index, proxy, progress, task_id):
        temp_file = self.temp_files[part_index]
        expected_size = end - start + 1

        if os.path.exists(temp_file) and os.path.getsize(temp_file) == expected_size:
            progress.update(task_id, advance=expected_size)
            return

        attempt = 0
        while attempt <= self.max_retries:
            try:
                headers = {'Range': f'bytes={start}-{end}'}
                mode = 'ab' if os.path.exists(temp_file) else 'wb'
                downloaded = os.path.getsize(temp_file) if os.path.exists(temp_file) else 0
                if downloaded > 0:
                    headers['Range'] = f'bytes={start + downloaded}-{end}'

                proxy_dict = {"http": proxy, "https": proxy} if proxy else None

                with requests.get(self.url, headers=headers, proxies=proxy_dict, stream=True,
                                  timeout=(30, 30), verify=self.verify_ssl) as r:
                    r.raise_for_status()
                    with open(temp_file, mode) as f:
                        progress.update(task_id, completed=downloaded)
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                progress.update(task_id, advance=len(chunk))
                return
            except Exception as e:
                attempt += 1
                print(f"⚠️ Thread-{part_index} 失败尝试 {attempt}/{self.max_retries}: {e}")
                if attempt > self.max_retries:
                    print(f"❌ Thread-{part_index} 最终失败")
                    return
                time.sleep(self.retry_wait * 60)

    def merge_parts(self):
        print("\n📦 正在进行合并操作,请等待......")
        with open(self.output, 'wb') as f_out:
            for temp_file in self.temp_files:
                with open(temp_file, 'rb') as f_in:
                    f_out.write(f_in.read())
        for temp_file in self.temp_files:
            os.remove(temp_file)
        print(f"✅ 合并完成：{self.output}")

    def load_failed_parts(self, file_size):
        part_size = file_size // self.num_threads
        parts_to_download = []

        for i in range(self.num_threads):
            start = i * part_size
            end = file_size - 1 if i == self.num_threads - 1 else (start + part_size - 1)
            expected_size = end - start + 1
            temp_file = self.temp_files[i]

            if not os.path.exists(temp_file) or os.path.getsize(temp_file) != expected_size:
                parts_to_download.append(i)

        return parts_to_download

    def test_proxy(self, proxy):
        try:
            r = requests.get("https://www.google.com/", proxies={"http": proxy, "https": proxy}, timeout=10)
            if r.status_code == 200:
                return True
        except:
            pass
        return False

    def start(self):
        file_size = self.get_file_size()
        if file_size == 0:
            raise Exception("无法获取文件大小，URL可能无效或服务器不支持 Range 请求")

        part_size = file_size // self.num_threads
        parts_to_download = self.load_failed_parts(file_size)

        if not parts_to_download:
            print("📂 所有分段已完成，无需重复下载，直接合并...")
            self.merge_parts()
            return

        threads = []
        with Progress(
                "[progress.description]{task.description}",
                BarColumn(),
                "[progress.percentage]{task.percentage:>3.0f}%",
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
        ) as progress:
            for i in parts_to_download:
                start = i * part_size
                end = file_size - 1 if i == self.num_threads - 1 else (start + part_size - 1)
                proxy = self.proxies[i % len(self.proxies)] if self.use_proxy else None

                if proxy and not self.test_proxy(proxy):
                    print(f"🚫 无效代理 Thread-{i}: {proxy}，跳过该线程")
                    continue

                task_id = progress.add_task(f"Thread-{i}", total=end - start + 1)
                t = threading.Thread(
                    target=self.download_range_with_rich,
                    args=(start, end, i, proxy, progress, task_id)
                )
                t.start()
                threads.append(t)

            for t in threads:
                t.join()

        remaining = self.load_failed_parts(file_size)
        if not remaining:
            self.merge_parts()
            client.send_notification(
                title="🏆  文件下载成功",
                body=f"文件{self.output}下载成功!",
                sound="shake",
                icon="https://c-ssl.dtstatic.com/uploads/item/201911/16/20191116010243_lavmv.thumb.1000_0.jpeg"
            )
        else:
            print(f"⏹️ 下载未完成，还有 {len(remaining)} 个分段未完成，稍后可重新运行以继续下载")
            client.send_notification(
                title="❌  文件下载失败",
                body=f"文件{self.output}下载失败!\n还有 {len(remaining)} 个分段未完成!",
                sound="shake",
                icon="https://c-ssl.dtstatic.com/uploads/item/201911/16/20191116010243_lavmv.thumb.1000_0.jpeg"
            )


def guess_file_name_from_url(url):
    parsed = urlparse(url)
    return os.path.basename(parsed.path) or "downloaded_file"


def main():
    parser = argparse.ArgumentParser(description="多线程断点续传下载器（支持代理/SSL/自动重试）")
    parser.add_argument("url", help="文件下载地址")
    parser.add_argument("--p", action="store_true", help="启用代理模式")
    parser.add_argument("--n", type=int, default=6, help="线程数量（默认6）")
    parser.add_argument("--name", type=str, help="输出文件名（默认根据URL推断）")
    parser.add_argument("--v", action="store_true", help="禁用SSL验证")
    args = parser.parse_args()

    url = args.url
    num_threads = args.n
    output_name = args.name or guess_file_name_from_url(url)
    use_proxy = args.p
    verify_ssl = not args.v

    proxy_pool = [
        "http://127.0.0.1:8890",
        "http://127.0.0.1:8891",
        "http://127.0.0.1:8892",
        "http://127.0.0.1:8893",
        "http://127.0.0.1:8894",
        "http://127.0.0.1:8895",
    ]

    downloader = Downloader(
        url=url,
        output=output_name,
        num_threads=num_threads,
        use_proxy=use_proxy,
        proxies=proxy_pool,
        max_retries=12,
        retry_wait=5,
        verify_ssl=verify_ssl
    )
    downloader.start()


if __name__ == "__main__":
    main()
