import copy
import socket
import threading
import time
import random
from trivia_questions import trivia_questions
from statistics import init_stats, update_stats
from colors import *
import json
import os

# Configuration
UDP_BROADCAST_PORT = 13117
MAGIC_COOKIE = 0xabcddcba
OFFER_MESSAGE_TYPE = 0x2
SERVER_NAME = "TriviaKing"
QUESTION_TIMEOUT = 10  # seconds

# Game state variables
game_won = False
game_won_lock = threading.Lock()
winner_name = None
winner_name_lock = threading.Lock()
TCP_PORT = None
tcp_socket = None

# Dictionaries to store client sockets, player statistics, and question statistics
client_sockets = {}
player_stats = {}
question_stats = {}
for name in trivia_questions:
    question_stats[name['question']] = [0, 0]  # [correct_answers, wrong_answers]




# Function to save statistics to JSON file
def save_statistics():
    with open('statistics.json', 'w') as f:
        json.dump({'player_stats': player_stats, 'question_stats': question_stats}, f)

# Function to load statistics from JSON file
def load_statistics():
    global player_stats, question_stats
    if os.path.exists('statistics.json'):
        with open('statistics.json', 'r') as f:
            data = json.load(f)
            player_stats = data['player_stats']
            question_stats = data['question_stats']




# this function is responsible for sending the broadcast message to the clients
def broadcast_offers(stop_event):
    # Create UDP socket
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    # Enable broadcasting mode
    udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    # Construct and send the broadcast message by concatenating the magic cookie, message type, and TCP port
    message = MAGIC_COOKIE.to_bytes(4, 'big') + OFFER_MESSAGE_TYPE.to_bytes(1, 'big') + TCP_PORT.to_bytes(2, 'big')
    # Send broadcast message every second until stop_event is set
    while not stop_event.is_set():
        udp_socket.sendto(message, ('<broadcast>', UDP_BROADCAST_PORT))
        print(f"{COLOR_BRIGHT_CYAN}Broadcast sent!{COLOR_RESET}")
        time.sleep(1)


# this function is responsible for accepting the connection from the clients
def accept_connection(tcp_socket, new_client_event):
    # Accept new client connection
    client_socket, address = tcp_socket.accept()
    global client_sockets
    # Receive client name
    try:
        name = client_socket.recv(1024).decode().strip()
        client_sockets[name] = client_socket
        print(f"{COLOR_GREEN}{name} ({address[0]}) joined the game.{COLOR_RESET}")
        new_client_event.set()  # Signal that a new client has joined
    except Exception as e:
        print(f"{COLOR_BRIGHT_RED}Error receiving client name from {address[0]}: {e}{COLOR_RESET}")


# this function is responsible for accepting the connections from the clients
# the function will run in the main thread
def accept_connections(timeout=10):
    # Create TCP socket
    global TCP_PORT
    global tcp_socket
    # Generate random port number and bind the socket because we don't want to use the same port every time
    while True:
        try:
            TCP_PORT = random.randint(49152, 65535)
            server_tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            tcp_socket = server_tcp_sock
            break
        except OSError:
            print(f"{COLOR_BRIGHT_RED}Port {TCP_PORT} is already in use. Trying another port...{COLOR_RESET}")
            continue
    tcp_socket.bind(('', TCP_PORT))
    tcp_socket.listen()

    # Start UDP broadcast
    start_time = time.time()
    new_client_event = threading.Event()
    stop_event = threading.Event()
    # we use function broadcast_offers to send the broadcast message to the clients
    udp_thread = threading.Thread(target=broadcast_offers, args=(stop_event,), daemon=True)
    udp_thread.start()

    print(f"{COLOR_BRIGHT_BLUE}Server started, listening on port {TCP_PORT}{COLOR_RESET}")
    # this part responsible for accepting the connection from the clients after the broadcast message sent
    # after the UDP broadcast message sent, the server will wait for 10 seconds to accept the connection from the clients
    while time.time() - start_time < timeout:
        accept_connections_thread = threading.Thread(target=accept_connection, args=(tcp_socket, new_client_event),
                                                     daemon=True)
        accept_connections_thread.start()
        accept_connections_thread.join(timeout=timeout - (time.time() - start_time))
        if new_client_event.is_set():
            new_client_event.clear()
            start_time = time.time()

    stop_event.set()
    udp_thread.join()


# this function is responsible for receiving the client's answer and checking if it is correct or not
# the argument of the function is the name of the client, the question, and the client_answers
# question is a dictionary that contains the question and the answer
# client_answers is a dictionary that contains the name of the client and the answer
def handle_client_answer(name, question, client_answers):
    answer_keys = {'Y': True, 'T': True, '1': True, 'N': False, 'F': False, '0': False}
    global game_won, winner_name, client_sockets
    try:
        # Receive answer from client
        sock = client_sockets[name]
        sock.settimeout(QUESTION_TIMEOUT)
        # Receive answer from client
        answer = sock.recv(1024).decode().strip().upper()
        # Validate answer
        if answer not in answer_keys.keys():
            print(f"{COLOR_BRIGHT_RED}Invalid answer received from {name}.{COLOR_RESET}")
            sock.sendall(f"Invalid answer, Needs to answer with {list(answer_keys.keys())}".encode())

        # Check if answer is correct
        correct = answer_keys[answer] == question['is_true']
        # Update client_answers dictionary
        client_answers[name] = correct

        if correct:
            question_stats[question['question']][0] += 1
        else:
            question_stats[question['question']][1] += 1

        if correct:
            with game_won_lock:
                if correct and not game_won:
                    game_won = True
                    with winner_name_lock:
                        winner_name = name
                    response_message = f"{COLOR_BRIGHT_GREEN}Correct! You win!{COLOR_RESET}\n"
                    print(f"{name} answered correctly and won the game!")
                elif correct and game_won:
                    with winner_name_lock:
                        response_message = f"{COLOR_BRIGHT_GREEN}Correct, but too late! {winner_name} has already won the game.{COLOR_RESET}\n"
        else:
            response_message = f"{COLOR_BRIGHT_RED}Incorrect. You lose.{COLOR_RESET}\n"
        sock.sendall(response_message.encode())
    except TimeoutError:
        print(f"{COLOR_BRIGHT_RED}Timeout receiving answer from {name}.{COLOR_RESET}")
    except Exception as e:
        print(f"{COLOR_BRIGHT_RED}Error receiving answer from {name}: {e}{COLOR_RESET}")


# this function is responsible for running the game and sending the questions to the clients
# the function will run in the main thread
# the function will send the welcome message to the clients
def run_game():
    global game_won, winner_name, client_sockets, game_won_lock, winner_name_lock, client_answer_copy

    with game_won_lock:
        game_won = False
    with winner_name_lock:
        winner_name = None

    # Check if any clients have joined the game
    if len(client_sockets) == 0:
        print(f"{COLOR_BRIGHT_YELLOW}No players joined. Restarting...{COLOR_RESET}")
        return









    # Send welcome message to all clients
    players_list = list(client_sockets.keys())
    players_string = '\n'.join(f"Player {i + 1}: {name}" for i, name in enumerate(players_list))
    for sock in client_sockets.values():
        try:
            welcome_message = (f"{COLOR_PURPLE}Welcome to the {SERVER_NAME} server, where we answer trivia questions."
                               f"\n{players_string}\n==\n{COLOR_RESET}")
            # Send welcome message
            sock.sendall(welcome_message.encode())
            question_instruction_message = f"{COLOR_BRIGHT_YELLOW}Answer with 'Y', 'T', '1' for True or 'N', 'F', '0' for False.\n{COLOR_RESET}"
            # Send instructions to clients on how to answer
            sock.sendall(question_instruction_message.encode())
        except Exception as e:
            print(f"{COLOR_BRIGHT_RED}Error sending welcome message: {e}{COLOR_RESET}")

    # New loop to handle repeating question on no correct answer
    question_attempt = 0
    copy_trivia_questions = copy.deepcopy(trivia_questions)
    max_attempts = len(copy_trivia_questions)  # Limit to number of available questions to avoid infinite loop

    # Send instructions to clients
    while question_attempt < max_attempts and not game_won:
        # Choose a random question
        question = random.choice(copy_trivia_questions)
        copy_trivia_questions.remove(question)  # Avoid repeating the same question
        print(f"{COLOR_BRIGHT_BLUE}Asking: {question['question']}{COLOR_RESET}")

        question_message = f"{COLOR_CYAN}True or false:{question['question']}{COLOR_RESET}\n"


        client_answers = {}
        client_answers_threads = []
        # Send question to all clients
        for name, sock in client_sockets.items():
            try:
                client_answers[name] = None
                # Send question to client
                sock.sendall(question_message.encode())
            except Exception as e:
                print(f"{COLOR_BRIGHT_RED}Error sending question to {name}: {e}{COLOR_RESET}")
            # Start a thread to handle client answer
            client_answer = threading.Thread(target=handle_client_answer, args=(name, question, client_answers))
            client_answers_threads.append(client_answer)
            client_answer.start()

        # Wait for all clients to answer
        for client_answer_thread in client_answers_threads:
            client_answer_thread.join(timeout=QUESTION_TIMEOUT)

        # Check if game was won (correct answer received)
        with game_won_lock:
            if not game_won or not any(client_answers.values()):
                # No correct answer received, or no answers at all
                print(f"{COLOR_BRIGHT_YELLOW}No correct answer. Repeating question...{COLOR_RESET}")
                for name, sock in client_sockets.items():
                    try:
                        sock.sendall(f"{COLOR_BRIGHT_YELLOW}No one answered correctly within the time limit.{COLOR_RESET}\n".encode())
                    except Exception as e:
                        print(f"{COLOR_BRIGHT_RED}Error sending no correct answer message to {name}: {e}{COLOR_RESET}")
                question_attempt += 1
            else:
                client_answer_copy = copy.deepcopy(client_answers)
                break  # Exit loop if game won or max attempts reached

    # Announcement to all clients
    if game_won:
        announcement = f"{COLOR_BRIGHT_GREEN}Game over! Congratulations to the winner: {winner_name}!{COLOR_RESET}\n"
    else:
        announcement = f"{COLOR_BRIGHT_RED}Game over! No winners this time.{COLOR_RESET}\n"

    for client_socket in client_sockets.values():
        try:
            client_socket.sendall(announcement.encode())
        except Exception as e:
            print(f"{COLOR_BRIGHT_RED}Error sending game outcome to a client: {e}{COLOR_RESET}")

    # Initialize statistics dictionaries and update stats
    init_stats(client_sockets, player_stats)
    update_stats(client_sockets, player_stats, question_stats, client_answer_copy, game_won, winner_name)


    # At the end of the game, before closing client sockets
    # Send closing message to all clients
    closing_message = f"{COLOR_PURPLE}Server is closing the connection. Please acknowledge.{COLOR_RESET}\n"
    for name, client_socket in client_sockets.items():
        try:
            client_socket.sendall(closing_message.encode())
            # Wait for acknowledgment
            ack = client_socket.recv(1024).decode().strip()
            if ack == "CLIENT_ACK":
                print(f"{COLOR_BRIGHT_GREEN}Acknowledgment received from {name}. Closing connection.{COLOR_RESET}")
        except Exception as e:
            print(f"{COLOR_BRIGHT_RED}Error sending closing message to {name}: {e}{COLOR_RESET}")
        finally:
            client_socket.close()


if __name__ == "__main__":
    load_statistics()
    while True:
        try:
            accept_connections()
            run_game()
            save_statistics()
        except Exception as e:
            print(f"Error during game loop: {e}")
        finally:
            # Clear client_sockets dictionary because we don't want to keep the previous clients
            client_sockets.clear()
