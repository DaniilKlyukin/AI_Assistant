import matplotlib.pyplot as plt
import numpy as np


def main():
    x = np.linspace(0, 2 * np.pi, 400)
    y = np.sin(x ** 2)

    plt.figure(figsize=(8, 4))
    plt.plot(x, y, label='sin(x^2)')
    plt.title('Simple Plot')
    plt.xlabel('x')
    plt.ylabel('y')
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
