import numpy as np 
import matplotlib.pyplot as plt 


data = np.load("data.npz")
msts = data['msts']

msts = (msts + 168)/8191 * 20 # тут случаем не 8192

plt.plot(msts[3]*1e3)
plt.show()