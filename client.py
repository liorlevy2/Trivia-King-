import random
import socket
import threading
import time
import select
from colors import *


# Configuration
UDP_PORT = 13117
MAGIC_COOKIE = 0xabcddcba
OFFER_MESSAGE_TYPE = 0x2
SERVER_IP = '0.0.0.0'
server_name = "TriviaKing"
tcp_socket = None


def listen_for_offers():
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    udp_socket.bind((SERVER_IP, UDP_PORT))
    print(f"{COLOR_BRIGHT_YELLOW}Client started, listening for offer requests...{COLOR_RESET}")
    while True:
        data, addr = udp_socket.recvfrom(1024)
        if len(data) >= 7:
            magic_cookie, message_type, server_port = (int.from_bytes(data[:4], 'big'), data[4],
                                                       int.from_bytes(data[5:7], 'big'))
            if magic_cookie == MAGIC_COOKIE and message_type == OFFER_MESSAGE_TYPE:
                print(f"{COLOR_BRIGHT_BLUE}Received offer from server {server_name} at address {addr[0]}, "
                      f"attempting to connect...{COLOR_RESET}")
                return addr[0], server_port


def connect_to_server(server_ip, server_port):
    global tcp_socket
    tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_socket.connect((server_ip, server_port))
    return tcp_socket


def send_name(name="Player"):
    global tcp_socket
    tcp_socket.sendall(f"{name}\n".encode())


def handle_user_input():
    global tcp_socket
    answer_keys = {'Y': True, 'T': True, '1': True, 'N': False, 'F': False, '0': False}
    start_time = time.time()
    while time.time() - start_time < 10:
        message = input()
        if message in answer_keys.keys():
            tcp_socket.sendall(message.encode())
            return None
        else:
            print(f"{COLOR_BRIGHT_RED}Invalid input. Please enter Y/T/1 for True, N/F/0 for False.{COLOR_RESET}")
            time.sleep(0.2)
    return None


def game_loop():
    global tcp_socket
    print(f"{COLOR_BRIGHT_YELLOW}Game started. Waiting for question...{COLOR_RESET}")
    while True:
        readable, _, _ = select.select([tcp_socket], [], [], 0.1)
        message = tcp_socket.recv(1024).decode()
        print(message)
        if "Server is closing the connection. Please acknowledge." in message:
            tcp_socket.sendall("CLIENT_ACK".encode())
            break  # Exiting the loop, so no need to set the input_event here.
        elif "true or false" in message.lower():
            input_thread = threading.Thread(target=handle_user_input, daemon=True)
            input_thread.start()
            input_thread.join(timeout=10)  # Timeout after 10 seconds


if __name__ == "__main__":
    while True:
        try:
            # state 1: listen for offers
            server_ip, server_port = listen_for_offers()

            # state 2: connect to server
            tcp_socket = connect_to_server(server_ip, server_port)
            random_names = ["Alice", "Bob", "Charlie", "David", "Eve", "Frank", "Grace", "Heidi", "Ivan", "Judy"]
            name = random.choice(random_names)
            send_name(name=name)

            # state 3: game mode
            game_loop()
            tcp_socket.close()
        except Exception as e:
            print(f"{COLOR_BRIGHT_RED}Error during game: {e}{COLOR_RESET}")
            continue
