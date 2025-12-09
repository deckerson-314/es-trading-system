import pickle
from deap import base, creator, tools

# Replicate BB_Genetic_v4.py setup
if hasattr(creator, "FitnessMulti"): del creator.FitnessMulti
if hasattr(creator, "Individual"): del creator.Individual
creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 1.0, 2.0, 2.0))
creator.create("Individual", list, fitness=creator.FitnessMulti)

try:
    with open(r"c:\Trading\ga_diagnostics_v4\ga_checkpoint_v4.pkl", "rb") as f:
        cp = pickle.load(f)
    hof = cp["hall_of_fame"]
    print(f"HOF Length: {len(hof)}")
    for i, ind in enumerate(hof):
        print(f"Ind {i} Valid: {ind.fitness.valid}")
        # print(f"Values: {ind.fitness.values}") 
except Exception as e:
    print(f"Error: {e}")
