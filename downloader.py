import os
import threading
import time
import json
import argparse
import requests
from urllib.parse import urlparse
from rich.progress import Progress, BarColumn, TimeRemainingColumn, DownloadColumn, TransferSpeedColumn
import urllib3

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
        self.failed_parts = []
        self.failed_log_path = f"{output}.failed_parts.json"

    def get_file_size(self):
        headers = requests.head(self.url, verify=self.verify_ssl).headers
        return int(headers.get('Content-Length', 0))

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
                                  timeout=30, verify=self.verify_ssl) as r:
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
                if attempt > self.max_retries:
                    self.failed_parts.append(part_index)
                    return
                time.sleep(self.retry_wait * 60)

    def merge_parts(self):
        with open(self.output, 'wb') as f_out:
            for temp_file in self.temp_files:
                with open(temp_file, 'rb') as f_in:
                    f_out.write(f_in.read())
        for temp_file in self.temp_files:
            os.remove(temp_file)
        if os.path.exists(self.failed_log_path):
            os.remove(self.failed_log_path)

    def load_failed_parts(self):
        if os.path.exists(self.failed_log_path):
            with open(self.failed_log_path, 'r') as f:
                return json.load(f)
        return list(range(self.num_threads))

    def save_failed_parts(self):
        if self.failed_parts:
            with open(self.failed_log_path, 'w') as f:
                json.dump(self.failed_parts, f)
        else:
            print("\n🎉 所有分段下载成功")

    def start(self):
        file_size = self.get_file_size()
        if file_size == 0:
            raise Exception("无法获取文件大小，URL可能无效或服务器不支持 Range 请求")

        part_size = file_size // self.num_threads
        parts_to_download = self.load_failed_parts()

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
                task_id = progress.add_task(f"Thread-{i}", total=end - start + 1)
                t = threading.Thread(target=self.download_range_with_rich, args=(start, end, i, proxy, progress, task_id))
                t.start()
                threads.append(t)

            for t in threads:
                t.join()

        self.save_failed_parts()

        if not self.failed_parts:
            self.merge_parts()
            print(f"✅ 合并完成：{self.output}")
        else:
            print("⏹️ 下载未完成，未执行合并")

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
        "http://127.0.0.1:8001",
        "http://127.0.0.1:8002",
        "http://127.0.0.1:8003",
        "http://127.0.0.1:8004",
        "http://127.0.0.1:8005",
        "http://127.0.0.1:8006",
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
