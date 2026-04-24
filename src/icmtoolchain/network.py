import platform
import socket
import subprocess
from typing import List, Optional, Tuple

from .adb import get_adb_executable
from .shell import Progress
from .utils import DEVNULL


def get_ip() -> str:
	make = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	make.settimeout(0)
	try:
		make.connect(("10.253.254.255", 1))
		ip = make.getsockname()[0]
	except Exception:
		ip = "127.0.0.1"
	finally:
		make.close()
	return ip

def ping_via_shell(ip: str, index: int, progress: Optional[Progress] = None) -> int:
	if progress and index % 15 == 0:
		progress.update(index / 255, f"Pinging {ip}")
	return subprocess.call([
		"ping",
		"-n" if platform.system() == "Windows" else "-c", "1",
		ip
	], stdout=DEVNULL, stderr=DEVNULL) == 0

async def ping(ip: str, index: int, accepted: List[str], progress: Optional[Progress] = None) -> None:
	if progress and index % 15 == 0:
		progress.update(index / 255, f"Pinging {ip}")
	import asyncio
	coroutine = await asyncio.create_subprocess_shell(
		f"ping {'-n' if platform.system() == 'Windows' else '-c'} 1 {ip}", stdout=DEVNULL, stderr=DEVNULL
	)
	await coroutine.wait()
	if coroutine.returncode == 0:
		accepted.append(ip)

async def ping_async(ip: Tuple[str, str, str], accepted: List[str], progress: Optional[Progress] = None) -> None:
	import asyncio
	tasks = list()
	for index in range(256):
		if str(index) == ip[2]:
			continue
		next_ip = "{}.{}".format(ip[0], index)
		task = asyncio.ensure_future(ping(next_ip, index, accepted, progress=progress))
		tasks.append(task)
	await asyncio.gather(*tasks, return_exceptions=True)

async def connect(ip: str, port: int, accepted: List[str], progress: Optional[Progress] = None) -> None:
	if len(accepted) > 0:
		return
	if progress and port % 15 == 0:
		progress.update(port / 65535, f"Connecting to {ip}:{str(port)}")
	import asyncio
	coroutine = await asyncio.create_subprocess_shell(
		get_adb_executable() + " connect " + ip + ":" + str(port), stdout=DEVNULL, stderr=DEVNULL
	)
	await coroutine.wait()
	if coroutine.returncode == 0:
		accepted.append(str(port))

async def connect_async(ip: str, accepted: List[str], progress: Optional[Progress] = None) -> None:
	import asyncio
	tasks = list()
	for index in range(1000, 65536):
		task = asyncio.ensure_future(connect(ip, index, accepted, progress=progress))
		tasks.append(task)
	await asyncio.gather(*tasks, return_exceptions=True)
