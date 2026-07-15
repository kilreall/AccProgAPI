import numpy as np 
import matplotlib.pyplot as plt 


data = np.load("trigger_20260715_151436.npz")
msts = data['msts']

msts = (msts + 168)/8191 * 20 # тут случаем не 8192

plt.plot(msts[5]*1e3)
plt.show()