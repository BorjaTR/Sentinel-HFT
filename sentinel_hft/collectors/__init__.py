"""Collectors for receiving traces from various sources."""

from .udp_collector import UDPCollector, UDPPacketHeader

__all__ = ['UDPCollector', 'UDPPacketHeader']
