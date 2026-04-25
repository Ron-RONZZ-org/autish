"""Partition management for disko command."""

import subprocess
from dataclasses import dataclass


@dataclass
class Partition:
    """Represents a disk partition."""

    device: str
    size: str
    used: str
    available: str
    percent: int
    mountpoint: str | None = None


def get_partition_info(device: str) -> Partition | None:
    """Get partition information using parted.
    
    Args:
        device: Device name (e.g., 'sda1' or '/dev/sda1')
        
    Returns:
        Partition object or None if not found
    """
    if not device.startswith("/dev/"):
        device = f"/dev/{device}"
    
    try:
        result = subprocess.run(
            ["sudo", "parted", "-l", device],
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        if result.returncode != 0:
            return None
        
        # Parse parted output (simplified)
        for line in result.stdout.split("\n"):
            if "Disk /dev/" in line:
                # Extract size info
                parts = line.split()
                if len(parts) >= 2:
                    return Partition(
                        device=device,
                        size=parts[-2] if len(parts) > 2 else "0",
                        used="",
                        available="",
                        percent=0,
                    )
        
        return None
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None


def is_mounted(device: str) -> bool:
    """Check if a device is mounted.
    
    Args:
        device: Device name (e.g., 'sda1' or '/dev/sda1')
        
    Returns:
        True if device is mounted, False otherwise
    """
    if not device.startswith("/dev/"):
        device = f"/dev/{device}"
    
    try:
        result = subprocess.run(
            ["mount"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return device in result.stdout
    except Exception:
        return False


def get_mount_point(device: str) -> str | None:
    """Get the mount point of a device.
    
    Args:
        device: Device name (e.g., 'sda1' or '/dev/sda1')
        
    Returns:
        Mount point path or None if not mounted
    """
    if not device.startswith("/dev/"):
        device = f"/dev/{device}"
    
    try:
        result = subprocess.run(
            ["mount"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        
        for line in result.stdout.split("\n"):
            if device in line:
                parts = line.split()
                if len(parts) >= 3 and parts[1] == "on":
                    return parts[2]
        
        return None
    except Exception:
        return None


def is_root_filesystem(device: str) -> bool:
    """Check if device contains the root filesystem.
    
    Args:
        device: Device name (e.g., 'sda1' or '/dev/sda1')
        
    Returns:
        True if device is mounted at / or contains /boot
    """
    mount_point = get_mount_point(device)
    if not mount_point:
        return False
    
    return mount_point in ["/", "/boot", "/boot/efi"]


def shrink_partition(
    device: str, new_size: str, force: bool = False
) -> tuple[bool, str]:
    """Shrink a partition.
    
    Args:
        device: Device name (e.g., 'sda1' or '/dev/sda1')
        new_size: New size (e.g., '50GB')
        force: Skip safety checks
        
    Returns:
        Tuple of (success, message)
    """
    if not device.startswith("/dev/"):
        device = f"/dev/{device}"
    
    # Safety checks
    if not force:
        if is_root_filesystem(device):
            return (False, "Ne eblas shrink de la radika dosierujo")
        
        if is_mounted(device):
            return (
                False,
                f"{device} estas munkita. Bonvolu elmuntigi antaŭ ol shrink."
            )
    
    try:
        result = subprocess.run(
            ["sudo", "parted", device, "resizepart", "1", new_size],
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        if result.returncode != 0:
            return (False, result.stderr.strip())
        
        return (True, f"Particio {device} shrinkita al {new_size}")
    except subprocess.TimeoutExpired:
        return (False, "Timeout dum shrinking")
    except Exception as e:
        return (False, str(e))


def create_partition(
    device: str, size: str, filesystem: str = "ext4", force: bool = False
) -> tuple[bool, str]:
    """Create a new partition.
    
    Args:
        device: Device name (e.g., 'sda' or '/dev/sda')
        size: Partition size (e.g., '50GB')
        filesystem: Filesystem type (ext4, ntfs, fat32, etc.)
        force: Skip safety checks
        
    Returns:
        Tuple of (success, message)
    """
    if not device.startswith("/dev/"):
        device = f"/dev/{device}"
    
    # Safety check
    if not force and is_mounted(device):
        return (
            False,
            f"{device} estas munkita. Bonvolu elmuntigi antaŭ ol krei particion."
        )
    
    try:
        # Get the next partition number
        result = subprocess.run(
            ["sudo", "parted", "-l", device],
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        # Count existing partitions (simplified)
        partition_count = result.stdout.count("Number")
        next_num = partition_count
        
        # Create partition
        result = subprocess.run(
            [
                "sudo",
                "parted",
                device,
                "mkpart",
                "primary",
                filesystem,
                "0%",
                size,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        if result.returncode != 0:
            return (False, result.stderr.strip())
        
        return (
            True,
            f"Nova particio {device}{next_num} kreitaen {filesystem}"
        )
    except subprocess.TimeoutExpired:
        return (False, "Timeout dum kreo de particio")
    except Exception as e:
        return (False, str(e))


def format_partition(
    device: str, filesystem: str, force: bool = False
) -> tuple[bool, str]:
    """Format a partition.
    
    Args:
        device: Device name (e.g., 'sda1' or '/dev/sda1')
        filesystem: Filesystem type (ext4, ntfs, fat32, etc.)
        force: Skip safety checks
        
    Returns:
        Tuple of (success, message)
    """
    if not device.startswith("/dev/"):
        device = f"/dev/{device}"
    
    # Safety checks
    if not force:
        if is_root_filesystem(device):
            return (False, "Ne eblas formati la radikan dosierujon!")
        
        if is_mounted(device):
            return (
                False,
                f"{device} estas munkita. Bonvolu elmuntigi antaŭ ol formati."
            )
    
    try:
        if filesystem == "ext4":
            cmd = ["sudo", "mkfs.ext4", "-F", device]
        elif filesystem == "ext3":
            cmd = ["sudo", "mkfs.ext3", "-F", device]
        elif filesystem == "ext2":
            cmd = ["sudo", "mkfs.ext2", "-F", device]
        elif filesystem == "ntfs":
            cmd = ["sudo", "mkfs.ntfs", "-F", device]
        elif filesystem == "fat32":
            cmd = ["sudo", "mkfs.fat", "-F", "32", device]
        elif filesystem == "vfat":
            cmd = ["sudo", "mkfs.vfat", "-F", "32", device]
        else:
            return (False, f"Nekonata dosierujo-tipo: {filesystem}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        
        if result.returncode != 0:
            return (False, result.stderr.strip())
        
        return (True, f"Particio {device} formatita kiel {filesystem}")
    except subprocess.TimeoutExpired:
        return (False, "Timeout dum formado")
    except Exception as e:
        return (False, str(e))
