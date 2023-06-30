import random

def generate_random_number(number):
    first_numbers = number[0:7]
    return f"{first_numbers}{random.randint(1000,9999)}"