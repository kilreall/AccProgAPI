import numpy as np 
import matplotlib.pyplot as plt 


data = np.load("V_m.npz")

arrays = [data[key] for key in data.files]

print(len(arrays))

#plt.show()