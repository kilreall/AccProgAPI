import numpy as np 
import matplotlib.pyplot as plt 


data = np.load(r"Interface\trigger_20260715_153242.npz")
msts = data['data']

msts = (msts + 168)/8191 * 20 # тут случаем не 8192

plt.plot(msts[5])
plt.show()