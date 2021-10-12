#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed May 5 12:57:19 2021
Modified July 13 2021

@author: afurlong

Reduced order model for a printed circuit heat excahnger in crossflow
"""

#import necessary libraries
#import cantera as ct
import numpy as np
import math
from scipy.integrate import solve_ivp
import time
#import sys
#from scipy.optimize import minimize
#from scipy.optimize import Bounds
from scipy.optimize import fsolve
from scipy.optimize import root
#import matplotlib.pyplot as plt
import csv

class crossflow_PCHE(object):
    """
    Crossflow heat exchanger model for a single set of printed circuit heat exchanger (PCHE) plates.
    
    Parameters
    -----
    reactant_in : list of four elements
        0. reactant composition, dict of compositions, units of mass%
        1. mass flow rate through reactant plate, units of kg/s 
        2. reactant inlet temperature, units K        
        3. reactant inlet absolute pressure, units of Pa
    
    utility_in : list of four elements
        0. utility composition, dict of compositions, units of mass%        
        1. mass flow rate through utility plate, units of kg/s         
        2. utility inlet temperature, units K        
        3. utility inlet absolute pressure, units of Pa
        
    dims : list of five elements
        0. reactant channel diameter, units of m
        1. utility channel diameter, units of m
        2. number of reactant channels, dimensionless
        3. number of utility channels, dimensionless
        4. wall thickness between channels, units of m
        5. plate thickness, units of m
        
        note : fuel plate geometry assumed to be identical to reactant plate geometry
            spacing between utiltiy channels assumed to be identical to spacing between reactant channels
        
        
    Returns
    -----
    N/A at presennt

    Reference
    -----
    See other methods in class.
    
    Applicability
    -----
    Applicable for laminar flow (Re <= 2300) OR turbulent flow (Re > 2300). Transitional flow is not considered. Flow is treated as either all developed or all transient.
    
    Not suitable for use beyond approximately ideal gas conditions.
            
    """
    
    def __init__(self, reactant, utility, fuel, dimensions):
        self.reactant = reactant
        self.utility = utility
        self.fuel = fuel
        self.dimensions = dimensions
        
        #grab #rows/#channels
        self.rows = self.dimensions[2]
        self.columns = self.dimensions[3]
        
        #set dimensions - cross sectional area
        self.reactant_cs = math.pi*self.dimensions[0]**2/8
        self.utility_cs = math.pi*self.dimensions[1]**2/8
        self.reactant_dh = math.pi*self.dimensions[0]/(2+math.pi)#self.reactant_cs**0.5
        self.utility_dh = math.pi*self.dimensions[1]/(2+math.pi)#self.utility_cs**0.5
        
        self.fuel_cs = self.reactant_cs
        self.fuel_dh = self.reactant_dh
        
        #aspect ratio for semicircular channels
        self.aspectratio = 0.5
        
        #set delta x/y/z to limit other calculation
        self.deltax = self.dimensions[1] + self.dimensions[4]
        self.deltay = self.dimensions[5]
        self.deltaz = self.dimensions[0] + self.dimensions[4]
        
        #define unit cell dimensions
        self.reactant_Vcell = self.reactant_cs*self.deltax
        self.utility_Vcell = self.utility_cs*self.deltaz
        self.reactantPlate_Vcell = self.deltax*self.deltay*self.deltaz - self.reactant_Vcell
        self.utilityPlate_Vcell = self.deltax*self.deltay*self.deltaz - self.utility_Vcell
        
        self.fuel_Vcell = self.reactant_Vcell
        self.fuelPlate_Vcell = self.reactantPlate_Vcell
        
        #define initial pressure profile (constant value)
        self.utility1_P = np.ones((self.rows, self.columns))*self.utility[3]
        self.reactant2_P = np.ones((self.rows, self.columns))*self.reactant[3]
        self.fuel3_P = np.ones((self.rows, self.columns))*self.fuel[3]
        self.reactant4_P = np.ones((self.rows, self.columns))*self.reactant[3]
        self.utility5_P = np.ones((self.rows, self.columns))*self.utility[3]


    
        #define heat transfer areas
        #r - reactant, u - utility, f - fuel
        #P - plate, F - fluid
        # self.hx_area_uPuF = (math.pi*self.dimensions[1]/2)*self.deltaz
        # self.hx_area_uPrF = self.dimensions[0]*self.deltax
        # self.hx_area_uPrP = self.deltax*self.deltaz - self.hx_area_uPrF
        # self.hx_area_rPuP = self.deltax*self.deltaz - self.hx_area_uPrF
        # self.hx_area_rPrF = (math.pi*self.dimensions[0]/2)*self.deltax
        # self.hx_area_boundary = self.deltax*self.deltaz-self.dimensions[1]*self.deltax
        # self.hx_area_boundary_solid = self.deltax*self.deltaz-self.hx_area_boundary
        
        self.hx_area_1 = self.dimensions[1]*self.deltaz #utility fluid 1 to utiltiy plate 5, utility fluid 5 to reactant plate 4
        self.hx_area_2 = self.deltax*self.deltaz - self.hx_area_1 #utility plate 1 to utility plate 5, utility plate 5 to reactant plate 4
        self.hx_area_3 = math.pi*self.dimensions[1]/2*self.deltaz #utility fluid 1 to utility plate 1, utility fluid 5 to utiltiy plate 5
        self.hx_area_4 = self.dimensions[0]*self.deltax #reactant fluid 2 to utility plate 1/fuel fluid 3 to reactant plate 2/reqactant fluid 4 to fuel plate 3
        self.hx_area_5 = self.deltax*self.deltaz - self.hx_area_4 #reactant plate 2 to utility plate 1, fuel plate 3 to reactant plate 2, reactant plate 4 to fuel plate 3
        self.hx_area_6 = math.pi*self.dimensions[0]/2*self.deltax #reactant fluid to plate, fuel fluid to plate
        
        
        #heat transfer areas within plates
        self.hx_area_rP_x = self.deltay*self.deltaz - self.reactant_cs
        self.hx_area_rP_z = self.deltax*self.deltay
        self.hx_area_uP_x = self.deltay*self.deltaz
        self.hx_area_uP_z = self.deltax*self.deltay - self.utility_cs
    
        self.hx_area_fP_x = self.hx_area_rP_x
        self.hx_area_fP_z = self.hx_area_rP_z
        
        #solid phase properties
        self.metalrho = 8000
        self.metalcp = 500
        self.metalk = 50
        
        #setup for initial viscosity parameters

        #data collected from GRI3.0
        #species must be sorted in the same order
        #low = 300K < T < 1000 K, high = 1000 K < T < 3500 K
        
        self.import_properties()
        
        #ideal gas constant - J mol-1 K-1
        self.GC = 8.3144626
        
        #create arrays to store speicifc heat capacities
        self.reactant2_cp, self.reactant4_cp, self.fuel3_cp, self.utility1_cp, self.utility_5_cp = map(np.copy, [np.zeros((self.dimensions[2], self.dimensions[3]))]*5)
        
        #self.mol_frac_and_cp()
        
        #set up positions for dimensionless length correlations
        #use center of each unit cell
        self.reactant_L = np.linspace(start = ((self.deltax)/2), 
                                      stop = (self.deltax*self.columns + (self.deltax)/2),
                                      num = self.columns)
        self.utility_L = np.linspace(start = ((self.deltaz)/2), 
                                      stop = (self.deltaz*self.rows + (self.deltaz)/2),
                                      num = self.rows)
        self.fuel_L = self.reactant_L
        
        #constant for heat transfer correlations to avoid setting multiple times
        self.C1 = 3.24 #uniform wall temperature
        self.C2 = 1 #local
        self.C3 = 0.409 #uniform wall temperature
        self.C4 = 1 #local
        self.gamma = -0.1 #midpoint taken
        
    def import_properties(self):
        '''
        Imports modified NASA thermo file and CHEMKIN transport file for 
        calculation of fluid properties.

        Returns
        -------
        None.

        '''
        thermo = open('thermo_oneline.dat', 'r')
        transport = open('transport.dat', 'r')
        
        self.cp_a1_list_high = {}
        self.cp_a2_list_high = {}
        self.cp_a3_list_high = {}
        self.cp_a4_list_high = {}
        self.cp_a5_list_high = {}
        self.cp_a1_list_low = {}
        self.cp_a2_list_low = {}
        self.cp_a3_list_low = {}
        self.cp_a4_list_low = {}
        self.cp_a5_list_low = {}
        self.epsOverKappa_list = {}
        self.sigma_list = {}
        self.dipole = {}
        self.polarizability = {}
        self.rotationalRelaxation = {}
        self.MW_list = {}
        self.shape = {}
        self.Tmin = {}
        
        for line in thermo:
            key, Tmin, a1high, a2high, a3high, a4high, a5high, a6high, a7high, a1low,\
                a2low, a3low, a4low, a5low, a6low, a7low = line.split()
            self.cp_a1_list_high[key] = float(a1high)
            self.cp_a2_list_high[key] = float(a2high)
            self.cp_a3_list_high[key] = float(a3high)
            self.cp_a4_list_high[key] = float(a4high)
            self.cp_a5_list_high[key] = float(a5high)
            self.cp_a1_list_low[key] = float(a1low)
            self.cp_a2_list_low[key] = float(a2low)
            self.cp_a3_list_low[key] = float(a3low)
            self.cp_a4_list_low[key] = float(a4low)
            self.cp_a5_list_low[key] = float(a5low)
            self.Tmin[key] = float(Tmin)
            
        for line in transport:
            key, shape, epsOverKappa, sigma, dipole, polarizability, rotRelax, \
                MW = line.split()
            self.epsOverKappa_list[key] = float(epsOverKappa)
            self.sigma_list[key] = float(sigma)
            self.dipole[key] = float(dipole)
            self.polarizability[key] = float(polarizability)
            self.rotationalRelaxation[key] = float(rotRelax)
            self.MW_list[key] = float(MW)
            self.shape[key] = int(shape)
        return
        
    def update_reactant(self, reactant):
        #replace the reactant - use to set new conditions like flow rate, temperature, or pressure
        self.reactant = reactant
        self.mol_frac_and_cp()
        return
    
    def update_fuel(self, fuel):
        #replace the reactant - use to set new conditions like flow rate, temperature, or pressure
        self.fuel = fuel
        self.mol_frac_and_cp()
        return
        
    def update_utility(self, utility):
        self.utility = utility
        self.mol_frac_and_cp()
        return
    
    def mol_frac_and_cp(self):
        #use molecular weights in init to convert
        #only convert when updated
        #only update coefficients for heat capacities when compositions are updates
        reactant_species = [*self.reactant[0]]
        utility_species = [*self.utility[0]]
        fuel_species = [*self.fuel[0]]
        nmol_reactant = np.zeros(len(reactant_species))
        nmol_utility = np.zeros(len(utility_species))
        nmol_fuel = np.zeros(len(fuel_species))
        
        #reset constants for specific heat capacities
        self.cp_a1_reactant2 = 0
        self.cp_a2_reactant2 = 0
        self.cp_a3_reactant2 = 0
        self.cp_a4_reactant2 = 0
        self.cp_a5_reactant2 = 0
        self.cp_a1_reactant4 = 0
        self.cp_a2_reactant4 = 0
        self.cp_a3_reactant4 = 0
        self.cp_a4_reactant4 = 0
        self.cp_a5_reactant4 = 0
        self.cp_a1_utility1 = 0
        self.cp_a2_utility1 = 0
        self.cp_a3_utility1 = 0
        self.cp_a4_utility1 = 0        
        self.cp_a5_utility1 = 0     
        self.cp_a1_utility5 = 0
        self.cp_a2_utility5 = 0
        self.cp_a3_utility5 = 0
        self.cp_a4_utility5 = 0        
        self.cp_a5_utility5 = 0  
        self.cp_a1_fuel3 = 0
        self.cp_a2_fuel3 = 0
        self.cp_a3_fuel3 = 0
        self.cp_a4_fuel3 = 0        
        self.cp_a5_fuel3 = 0      
        
        for i in range(len(reactant_species)):
            nmol_reactant[i] = self.reactant[0][reactant_species[i]]/self.MW_list[reactant_species[i]]
            self.cp_a1_reactant2 = self.cp_a1_reactant2 + nmol_reactant[i]*(self.cp_a1_list_low[reactant_species[i]]*np.less_equal(self.reactant2_T, 1000) + self.cp_a1_list_high[reactant_species[i]]*np.greater(self.reactant2_T, 1000)) 
            self.cp_a2_reactant2 = self.cp_a2_reactant2 + nmol_reactant[i]*(self.cp_a2_list_low[reactant_species[i]]*np.less_equal(self.reactant2_T, 1000) + self.cp_a2_list_high[reactant_species[i]]*np.greater(self.reactant2_T, 1000)) 
            self.cp_a3_reactant2 = self.cp_a3_reactant2 + nmol_reactant[i]*(self.cp_a3_list_low[reactant_species[i]]*np.less_equal(self.reactant2_T, 1000) + self.cp_a3_list_high[reactant_species[i]]*np.greater(self.reactant2_T, 1000)) 
            self.cp_a4_reactant2 = self.cp_a4_reactant2 + nmol_reactant[i]*(self.cp_a4_list_low[reactant_species[i]]*np.less_equal(self.reactant2_T, 1000) + self.cp_a4_list_high[reactant_species[i]]*np.greater(self.reactant2_T, 1000)) 
            self.cp_a5_reactant2 = self.cp_a5_reactant2 + nmol_reactant[i]*(self.cp_a5_list_low[reactant_species[i]]*np.less_equal(self.reactant2_T, 1000) + self.cp_a5_list_high[reactant_species[i]]*np.greater(self.reactant2_T, 1000)) 
            self.cp_a1_reactant4 = self.cp_a1_reactant4 + nmol_reactant[i]*(self.cp_a1_list_low[reactant_species[i]]*np.less_equal(self.reactant4_T, 1000) + self.cp_a1_list_high[reactant_species[i]]*np.greater(self.reactant4_T, 1000)) 
            self.cp_a2_reactant4 = self.cp_a2_reactant4 + nmol_reactant[i]*(self.cp_a2_list_low[reactant_species[i]]*np.less_equal(self.reactant4_T, 1000) + self.cp_a2_list_high[reactant_species[i]]*np.greater(self.reactant4_T, 1000)) 
            self.cp_a3_reactant4 = self.cp_a3_reactant4 + nmol_reactant[i]*(self.cp_a3_list_low[reactant_species[i]]*np.less_equal(self.reactant4_T, 1000) + self.cp_a3_list_high[reactant_species[i]]*np.greater(self.reactant4_T, 1000)) 
            self.cp_a4_reactant4 = self.cp_a4_reactant4 + nmol_reactant[i]*(self.cp_a4_list_low[reactant_species[i]]*np.less_equal(self.reactant4_T, 1000) + self.cp_a4_list_high[reactant_species[i]]*np.greater(self.reactant4_T, 1000)) 
            self.cp_a5_reactant4 = self.cp_a5_reactant4 + nmol_reactant[i]*(self.cp_a5_list_low[reactant_species[i]]*np.less_equal(self.reactant4_T, 1000) + self.cp_a5_list_high[reactant_species[i]]*np.greater(self.reactant4_T, 1000)) 

        for i in range(len(utility_species)):
            nmol_utility[i] = self.utility[0][utility_species[i]]/self.MW_list[utility_species[i]]
            self.cp_a1_utility1 = self.cp_a1_utility1 + nmol_utility[i]*(self.cp_a1_list_low[utility_species[i]]*np.less_equal(self.utility1_T, 1000) + self.cp_a1_list_high[utility_species[i]]*np.greater(self.utility1_T, 1000)) 
            self.cp_a2_utility1 = self.cp_a2_utility1 + nmol_utility[i]*(self.cp_a2_list_low[utility_species[i]]*np.less_equal(self.utility1_T, 1000) + self.cp_a2_list_high[utility_species[i]]*np.greater(self.utility1_T, 1000)) 
            self.cp_a3_utility1 = self.cp_a3_utility1 + nmol_utility[i]*(self.cp_a3_list_low[utility_species[i]]*np.less_equal(self.utility1_T, 1000) + self.cp_a3_list_high[utility_species[i]]*np.greater(self.utility1_T, 1000)) 
            self.cp_a4_utility1 = self.cp_a4_utility1 + nmol_utility[i]*(self.cp_a4_list_low[utility_species[i]]*np.less_equal(self.utility1_T, 1000) + self.cp_a4_list_high[utility_species[i]]*np.greater(self.utility1_T, 1000)) 
            self.cp_a5_utility1 = self.cp_a5_utility1 + nmol_utility[i]*(self.cp_a5_list_low[utility_species[i]]*np.less_equal(self.utility1_T, 1000) + self.cp_a5_list_high[utility_species[i]]*np.greater(self.utility1_T, 1000)) 
            self.cp_a1_utility5 = self.cp_a1_utility5 + nmol_utility[i]*(self.cp_a1_list_low[utility_species[i]]*np.less_equal(self.utility5_T, 1000) + self.cp_a1_list_high[utility_species[i]]*np.greater(self.utility1_T, 1000)) 
            self.cp_a2_utility5 = self.cp_a2_utility5 + nmol_utility[i]*(self.cp_a2_list_low[utility_species[i]]*np.less_equal(self.utility5_T, 1000) + self.cp_a2_list_high[utility_species[i]]*np.greater(self.utility5_T, 1000)) 
            self.cp_a3_utility5 = self.cp_a3_utility5 + nmol_utility[i]*(self.cp_a3_list_low[utility_species[i]]*np.less_equal(self.utility5_T, 1000) + self.cp_a3_list_high[utility_species[i]]*np.greater(self.utility5_T, 1000)) 
            self.cp_a4_utility5 = self.cp_a4_utility5 + nmol_utility[i]*(self.cp_a4_list_low[utility_species[i]]*np.less_equal(self.utility5_T, 1000) + self.cp_a4_list_high[utility_species[i]]*np.greater(self.utility5_T, 1000)) 
            self.cp_a5_utility5 = self.cp_a5_utility5 + nmol_utility[i]*(self.cp_a5_list_low[utility_species[i]]*np.less_equal(self.utility5_T, 1000) + self.cp_a5_list_high[utility_species[i]]*np.greater(self.utility5_T, 1000)) 

        for i in range(len(fuel_species)):
            nmol_fuel[i] = self.fuel[0][fuel_species[i]]/self.MW_list[fuel_species[i]]
            self.cp_a1_fuel3 = self.cp_a1_fuel3 + nmol_fuel[i]*(self.cp_a1_list_low[fuel_species[i]]*np.less_equal(self.fuel3_T, 1000) + self.cp_a1_list_high[fuel_species[i]]*np.greater(self.fuel3_T, 1000)) 
            self.cp_a2_fuel3 = self.cp_a2_fuel3 + nmol_fuel[i]*(self.cp_a2_list_low[fuel_species[i]]*np.less_equal(self.fuel3_T, 1000) + self.cp_a2_list_high[fuel_species[i]]*np.greater(self.fuel3_T, 1000)) 
            self.cp_a3_fuel3 = self.cp_a3_fuel3 + nmol_fuel[i]*(self.cp_a3_list_low[fuel_species[i]]*np.less_equal(self.fuel3_T, 1000) + self.cp_a3_list_high[fuel_species[i]]*np.greater(self.fuel3_T, 1000)) 
            self.cp_a4_fuel3 = self.cp_a4_fuel3 + nmol_fuel[i]*(self.cp_a4_list_low[fuel_species[i]]*np.less_equal(self.fuel3_T, 1000) + self.cp_a4_list_high[fuel_species[i]]*np.greater(self.fuel3_T, 1000)) 
            self.cp_a5_fuel3 = self.cp_a5_fuel3 + nmol_fuel[i]*(self.cp_a5_list_low[fuel_species[i]]*np.less_equal(self.fuel3_T, 1000) + self.cp_a5_list_high[fuel_species[i]]*np.greater(self.fuel3_T, 1000)) 

        self.cp_a1_reactant2 = self.cp_a1_reactant2/nmol_reactant.sum()
        self.cp_a2_reactant2 = self.cp_a2_reactant2/nmol_reactant.sum()
        self.cp_a3_reactant2 = self.cp_a3_reactant2/nmol_reactant.sum()
        self.cp_a4_reactant2 = self.cp_a4_reactant2/nmol_reactant.sum()
        self.cp_a5_reactant2 = self.cp_a5_reactant2/nmol_reactant.sum()
        self.cp_a1_reactant4 = self.cp_a1_reactant4/nmol_reactant.sum()
        self.cp_a2_reactant4 = self.cp_a2_reactant4/nmol_reactant.sum()
        self.cp_a3_reactant4 = self.cp_a3_reactant4/nmol_reactant.sum()
        self.cp_a4_reactant4 = self.cp_a4_reactant4/nmol_reactant.sum()
        self.cp_a5_reactant4 = self.cp_a5_reactant4/nmol_reactant.sum()
        
        self.cp_a1_utility1 = self.cp_a1_utility1/nmol_utility.sum()
        self.cp_a2_utility1 = self.cp_a2_utility1/nmol_utility.sum()
        self.cp_a3_utility1 = self.cp_a3_utility1/nmol_utility.sum()
        self.cp_a4_utility1 = self.cp_a4_utility1/nmol_utility.sum()
        self.cp_a5_utility1 = self.cp_a5_utility1/nmol_utility.sum()
        self.cp_a1_utility5 = self.cp_a1_utility5/nmol_utility.sum()
        self.cp_a2_utility5 = self.cp_a2_utility5/nmol_utility.sum()
        self.cp_a3_utility5 = self.cp_a3_utility5/nmol_utility.sum()
        self.cp_a4_utility5 = self.cp_a4_utility5/nmol_utility.sum()
        self.cp_a5_utility5 = self.cp_a5_utility5/nmol_utility.sum()
        
        self.cp_a1_fuel3 = self.cp_a1_fuel3/nmol_fuel.sum()
        self.cp_a2_fuel3 = self.cp_a2_fuel3/nmol_fuel.sum()
        self.cp_a3_fuel3 = self.cp_a3_fuel3/nmol_fuel.sum()
        self.cp_a4_fuel3 = self.cp_a4_fuel3/nmol_fuel.sum()
        self.cp_a5_fuel3 = self.cp_a5_fuel3/nmol_fuel.sum()
        
        reactant_molefrac = np.divide(nmol_reactant, nmol_reactant.sum())
        utility_molefrac = np.divide(nmol_utility, nmol_utility.sum())
        fuel_molefrac = np.divide(nmol_fuel, nmol_fuel.sum())
            
        self.reactant_molefrac = dict(zip(reactant_species, reactant_molefrac))
        self.utility_molefrac = dict(zip(utility_species, utility_molefrac))
        self.fuel_molefrac = dict(zip(fuel_species, fuel_molefrac))
        
        self.reactant_MW = 0
        self.utility_MW = 0
        self.fuel_MW = 0
        
        for i in range(len(reactant_species)):
            self.reactant_MW = self.reactant_MW + reactant_molefrac[i]*self.MW_list[reactant_species[i]]
        for i in range(len(utility_species)):
            self.utility_MW = self.utility_MW + utility_molefrac[i]*self.MW_list[utility_species[i]]
        for i in range(len(fuel_species)):
            self.fuel_MW = self.fuel_MW + fuel_molefrac[i]*self.MW_list[fuel_species[i]]

    def ff_Nu(self, fluid):
        """
        Evaluates the friction factors and Nusselt numbers for laminar and 
        turbulent flow for a given fluid

        Parameters
        ----------
        fluid : string
            String containing 'reactant', 'utility', or 'fuel' to pull class 
            variables for the given fluid

        Returns
        -------
        frictionfactor : array
            Array of floats containing friction factors for the given fluid in 
            laminar or turbulent flow
        nusselt : array
            Array of floats containing Nusself numbers for the given luid in
            laminar or turbulent flow
        
        Applicability
        -----
        Applicable for developing laminar flow (Re <= 2300), or fully developed
        turbulent flow in a smooth channel (Re > 2300). Transitional flow is 
        not considered.
        
        Reference
        ------
        Muzychka, Y. S., & Yovanovich, M. M. (2009). Pressure Drop in Laminar 
        Developing Flow in Noncircular Ducts: A Scaling and Modeling Approach. 
        Journal of Fluids Engineering, 131(11). 
        https://doi.org/10.1115/1.4000377
        
        Muzychka, Y. S., & Yovanovich, M. M. (2004). Laminar Forced Convection 
        Heat Transfer in the Combined Entry Region of Non-Circular Ducts. 
        Journal of Heat Transfer, 126(1), 54–61. 
        https://doi.org/10.1115/1.1643752
        
        Gnielinski correlation for turbulent flow

        """
        
        #evaluate L+ for each fluid (dimensionless position for use in friction factor correlations)
        if fluid == 'reactant2':
            Lplus = self.reactant2_mu*self.reactant_L/(self.reactant[1]/self.rows)
            reynolds = self.reactant2_Re
            
            Pr = self.reactant2_Pr
            zstar = (self.reactant_L/self.reactant_dh)/(reynolds*Pr)

        elif fluid == 'reactant4':
            Lplus = self.reactant4_mu*self.reactant_L/(self.reactant[1]/self.rows)
            reynolds = self.reactant4_Re
            
            Pr = self.reactant4_Pr
            zstar = (self.reactant_L/self.reactant_dh)/(reynolds*Pr)
        
        elif fluid == 'utility1':
            Lplus = (self.utility1_mu.transpose()*self.utility_L).transpose()/(self.utility[1]/self.columns)
            reynolds = self.utility1_Re
            
            Pr = self.utility1_Pr
            zstar = ((self.utility_L/self.reactant_dh)/((reynolds*Pr).transpose())).transpose()

        elif fluid == 'utility5':
            Lplus = (self.utility5_mu.transpose()*self.utility_L).transpose()/(self.utility[1]/self.columns)
            reynolds = self.utility5_Re
            
            Pr = self.utility5_Pr
            zstar = ((self.utility_L/self.reactant_dh)/((reynolds*Pr).transpose())).transpose()
        
        elif fluid == 'fuel3':
            Lplus = self.fuel3_mu*self.fuel_L/(self.fuel[1]/self.rows)
            reynolds = self.fuel3_Re
            
            Pr = self.fuel3_Pr
            zstar = (self.fuel_L/self.fuel_dh)/(reynolds*Pr)
                       
        else:
            print('Incorrect fluid selected for friction factor!')
        
        m = 2.27 + 1.65*Pr**(1/3)
        fPr = 0.564/((1+(1.664*Pr**(1/6))**(9/2))**(2/9))
        
        laminar = np.less_equal(reynolds, 2300)
        turbulent = np.greater(reynolds, 2300)
        
        laminar_f = ((3.44 * Lplus**-0.5)**2 + (12 / (self.aspectratio**0.5 * (1 + self.aspectratio) * (1 - 192*self.aspectratio * math.pi**-5 * math.tanh(math.pi / (2*self.aspectratio)))))**2)**0.5/reynolds
        turbulent_f = (0.79*np.log(reynolds) - 1.64)**-2/4
        frictionfactor = laminar*laminar_f + turbulent*turbulent_f
        
        #this might need np.power instead of exponents
        nusselt_laminar = ((self.C4*fPr/zstar**0.5)**m + ((self.C2*self.C3*(laminar_f*reynolds/zstar)**(1/3))**5 + (self.C1*(laminar_f*reynolds/(8*math.pi**0.5*self.aspectratio**self.gamma)))**5)**(m/5))**(1/m)
        nusselt_turbulent = ((turbulent_f/2)*(reynolds-1000)*Pr)/(1+12.7*(turbulent_f/2)**0.5 * (Pr**(2/3) - 1))
        nusselt = laminar*nusselt_laminar + turbulent*nusselt_turbulent
        
        # if np.isnan(nusselt).any() == True or np.isnan(frictionfactor).any() == True:
        #     print('Nusselt/FF failed')
        #     #sys.exit()
        
        return frictionfactor, nusselt
        
    def properties(self, fluid):
        """
        Evaluate the viscosity and thermal conductivity of an ideal gas as a f
        unction of temperature using Wilke's approach given in Bird, Stewart, 
        and Lightfoot.
        
        Best suited for a minimal number of species (i.e. eliminate minor 
        species present) as the time to solve is exponentially reliant on the 
        number of species for interaction parameters.

        Parameters
        ----------
        fluid : String
            Fluid name, either 'reactant', 'utility', or 'fuel'. Uses this 
            information to select the correct set of temperatures and 
            compositions.

        Returns
        -------
        viscosity_mixture : Array, float
            Viscosity of the given fluid, units of Pa.s.
            
        k_mixture : Array, float
            Thermal conductivity of the fluid, units of W m-1 K-1.
            
        Applicability
        -----
        Applicable for small molecules, set for molecules up to ethane. Other 
        species can be added to the list in object initialization.
        
        Reference
        -----
        Bird, R. B., Stewart, W. E., & Lightfoot, E. N. (1966). 
        Transport Phenomena. Brisbane, QLD, Australia: 
        John Wiley and Sons (WIE). - note 2001 edition used for interaction
        parameters. Methodology for viscosity from Chapter 1.4, tabulated data 
        from Appendix E.1.
        
        CHEMKIN Manual - Warnatz model for thermal conductivity
        
        """
        #grab fluid composition, update cp
        if fluid == 'reactant2':
            composition = self.reactant[0]
            molfractions = self.reactant_molefrac
            temperatures = self.reactant2_T
            pressures = self.reactant2_P
            self.reactant2_rho = self.reactant2_P*self.reactant_MW/self.GC/self.reactant2_T/1000
            self.reactant2_cp = self.cp_a1_reactant2 + self.cp_a2_reactant2*temperatures + self.cp_a3_reactant2*np.power(temperatures, 2) + self.cp_a4_reactant2*np.power(temperatures, 3) + self.cp_a5_reactant2*np.power(temperatures, 4)
            self.reactant2_cp = self.reactant2_cp*self.GC/self.reactant_MW*1000 #to J/mol K, to J/kg K
        
        elif fluid == 'reactant4':
            composition = self.reactant[0]
            molfractions = self.reactant_molefrac
            temperatures = self.reactant4_T
            pressures = self.reactant4_P
            self.reactant4_rho = self.reactant4_P*self.reactant_MW/self.GC/self.reactant4_T/1000
            self.reactant4_cp = self.cp_a1_reactant4 + self.cp_a2_reactant4*temperatures + self.cp_a3_reactant4*np.power(temperatures, 2) + self.cp_a4_reactant4*np.power(temperatures, 3) + self.cp_a5_reactant4*np.power(temperatures, 4)
            self.reactant4_cp = self.reactant4_cp*self.GC/self.reactant_MW*1000 #to J/mol K, to J/kg K
            
        elif fluid == 'utility1':
            composition = self.utility[0]
            molfractions = self.utility_molefrac
            temperatures = self.utility1_T
            pressures = self.utility1_P
            self.utility1_rho = self.utility1_P*self.utility_MW/self.GC/self.utility1_T/1000
            self.utility1_cp = self.cp_a1_utility1 + self.cp_a2_utility1*temperatures + self.cp_a3_utility1*np.power(temperatures, 2) + self.cp_a4_utility1*np.power(temperatures, 3) + self.cp_a5_utility1*np.power(temperatures, 4)
            self.utility1_cp = self.utility1_cp*self.GC/self.utility_MW*1000 #to J/mol K, to J/kg K
        elif fluid == 'utility5':
            composition = self.utility[0]
            molfractions = self.utility_molefrac
            temperatures = self.utility5_T
            pressures = self.utility5_P
            self.utility5_rho = self.utility5_P*self.utility_MW/self.GC/self.utility5_T/1000
            self.utility5_cp = self.cp_a1_utility5 + self.cp_a2_utility5*temperatures + self.cp_a3_utility5*np.power(temperatures, 2) + self.cp_a4_utility5*np.power(temperatures, 3) + self.cp_a5_utility5*np.power(temperatures, 4)
            self.utility5_cp = self.utility5_cp*self.GC/self.utility_MW*1000 #to J/mol K, to J/kg K
            
        elif fluid == 'fuel3':
            composition = self.fuel[0]
            molfractions = self.fuel_molefrac
            temperatures = self.fuel3_T
            pressures = self.fuel3_P
            self.fuel3_rho = self.fuel3_P*self.fuel_MW/self.GC/self.fuel3_T/1000
            self.fuel3_cp = self.cp_a1_fuel3 + self.cp_a2_fuel3*temperatures + self.cp_a3_fuel3*np.power(temperatures, 2) + self.cp_a4_fuel3*np.power(temperatures, 3) + self.cp_a5_fuel3*np.power(temperatures, 4)
            self.fuel3_cp = self.fuel3_cp*self.GC/self.utility_MW*1000 #to J/mol K, to J/kg K
        else:
            print('Incorrect fluid selected for properties update!')
            
        #extract list of species
        species = [*composition]
        nspecies = len(species)
        
        #create arrays for fluids and intermediate calculations
        viscosity, Tstar, omega, ki, cpi, omega11, cvi, cvitrans, cvirot, \
            cvivib, Dkk, Z298, ZT,  F298, FT, ftrans, frot, fvib, A, B = map(np.copy, [np.zeros((self.dimensions[2], self.dimensions[3], nspecies))]*20)
        phi = np.zeros((self.dimensions[2], self.dimensions[3], nspecies**2))
        viscosity_mixture, k_mixture, viscCF = map(np.copy, [np.zeros((self.dimensions[2], self.dimensions[3]))]*3)
        
        # if temperatures.min() < 0:
        #     print('temperatures < 0, properties failed')
            #sys.exit()
        
        #calculate values for arrays
        for i in range(nspecies):
            Tstar[:, :, i] = temperatures/self.epsOverKappa_list[species[i]]
            omega[:, :, i] = 1.16145/(np.power(Tstar[:, :, i], 0.14874)) + 0.52487/(np.exp(0.77320*Tstar[:, :, i])) + 2.16178/(np.exp(2.43787*Tstar[:, :, i]))
            viscosity[:, :, i] = (2.6693 * (10**(-5)) * np.sqrt(self.MW_list[species[i]]*temperatures) / (self.sigma_list[species[i]]**2 * omega[:, :, i]))*98.0665/1000
            omega11[:, :, i] = 1.06036/(np.power(Tstar[:, :, i], 0.15610)) + 0.19300/(np.exp(0.47635*Tstar[:, :, i])) + 1.03587/(np.exp(1.52996*Tstar[:, :, i])) + 1.76474/(np.exp(3.89411*Tstar[:, :, i]))
            
            #apply viscosity correction factor for water
            if species[i] == 'H2O':
                viscCF = (-7.19443*10**-12)*np.power(temperatures, 3) + (1.27546*10**-8)*np.power(temperatures,2) + (8.69573*10**-5)*np.power(temperatures, 1) + 0.768920462
                viscosity[:, :, i] = viscosity[:, :, i]*viscCF

        for i in range(nspecies):
            cpi[:, :, i] = (self.cp_a1_list_low[species[i]]*np.less_equal(temperatures, 1000) + self.cp_a1_list_high[species[i]]*np.greater(temperatures, 1000)) + \
                            (self.cp_a2_list_low[species[i]]*np.less_equal(temperatures, 1000) + self.cp_a2_list_high[species[i]]*np.greater(temperatures, 1000))*temperatures + \
                            (self.cp_a3_list_low[species[i]]*np.less_equal(temperatures, 1000) + self.cp_a3_list_high[species[i]]*np.greater(temperatures, 1000))*np.power(temperatures, 2) + \
                            (self.cp_a4_list_low[species[i]]*np.less_equal(temperatures, 1000) + self.cp_a4_list_high[species[i]]*np.greater(temperatures, 1000))*np.power(temperatures, 3) + \
                            (self.cp_a5_list_low[species[i]]*np.less_equal(temperatures, 1000) + self.cp_a5_list_high[species[i]]*np.greater(temperatures, 1000))*np.power(temperatures, 4)
            cpi[:, :, i] = cpi[:, :, i]*self.GC/self.MW_list[species[i]] * 1000
            cvi[:, :, i] = cpi[:, :, i] - self.GC / self.MW_list[species[i]] * 1000

            FT[:, :, i] = 1 + math.pi**(3/2)/2*(self.epsOverKappa_list[species[i]] * 1/temperatures)**(1/2) + \
                ((math.pi**2)/4 + 2)*(self.epsOverKappa_list[species[i]] / temperatures) + \
                math.pi**(3/2)*(self.epsOverKappa_list[species[i]]/temperatures)**(3/2)
                
            F298[:, :, i] = 1 + math.pi**(3/2)/2*(self.epsOverKappa_list[species[i]] * 1/298)**(1/2) + \
                ((math.pi**2)/4 + 2)*(self.epsOverKappa_list[species[i]] / 298) + \
                math.pi**(3/2)*(self.epsOverKappa_list[species[i]]/298)**(3/2)
            
            ZT = self.rotationalRelaxation[species[i]]*F298/FT

            density = pressures*self.MW_list[species[i]]/self.GC/temperatures/1000

            #######
            ##NOTE: Dkk should be multiplied by 10^^20, but the results are 
            ##showing a need to be multiplied by 10^32 for different molecules
            #######

            Dkk[:, :, i] = 3/16*(2*math.pi*(1.38064852*10**-23)**3*np.power(temperatures, 3)/self.MW_list[species[i]]*1000)**0.5/(pressures*math.pi*self.sigma_list[species[i]]**2*omega11[:, :, i])*(10**32)

            cvitrans[:, :, i] = 3/2*self.GC/self.MW_list[species[i]]*1000
            cvirot[:, :, i] = (np.equal(self.shape[species[i]], 0) * 0 +\
                               np.equal(self.shape[species[i]], 1) * 1 +\
                               np.equal(self.shape[species[i]], 2) * 3/2)
            
            cvivib[:, :, i] = (np.equal(self.shape[species[i]], 0) * 0 + \
                               np.equal(self.shape[species[i]], 1) * (cvi[:, :, i] - 5/2*self.GC/self.MW_list[species[i]]*1000) +\
                               np.equal(self.shape[species[i]], 2) * (cvi[:, :, i] - 3 * self.GC/self.MW_list[species[i]]*1000))
                
            A[:, :, i] = 5/2 - density*Dkk[:, :, i]/viscosity[:, :, i]
            B[:, :, i] = ZT[:, :, i] + 2/math.pi*(5/3*cvirot[:, :, i] + density*Dkk[:, :, i]/viscosity[:, :, i])
            
            cvirot[:, :, i] = cvirot[:, :, i] * self.GC / self.MW_list[species[i]] * 1000

            ftrans[:, :, i] = 5/2*(1-2/math.pi*cvirot[:, :, i]/cvitrans[:, :, i]*A[:, :, i]/B[:, :, i])
            frot[:, :, i] = density*Dkk[:, :, i]/viscosity[:, :, i]*(1+2/math.pi*A[:, :, i]/B[:, :, i])
            fvib[:, :, i] = density*Dkk[:, :, i]/viscosity[:, :, i]
            
            #factor of 100 applied  based on tabulated data
            ki[:, :, i] = viscosity[:, :, i]*(ftrans[:, :, i]*cvitrans[:, :, i] + frot[:, :, i]*cvirot[:, :, i] + fvib[:, :, i]*cvivib[:, :, i])
            #cpi[:, :, i] = self.cp_a_list[species[i]] + self.cp_b_list[species[i]]*temperatures + self.cp_c_list[species[i]]*np.power(temperatures, 2) + self.cp_d_list[species[i]]*np.power(temperatures, -2)
            #ki[:, :, i] = (cpi[:, :, i] + 5/4)*8314.4626*viscosity[:, :, i]/self.MW_list[species[i]]
                    
        #calculate values of phi for each interaction -- use 3D array with one 2D array for every pair
        #this is made exponentially slower for every added species
        for i in range(nspecies):
            for j in range(nspecies):
                #phi[:, :, nspecies*i + j] = 1/(8**0.5) * (1 + self.MW_list[species[i]]/self.MW_list[species[j]])**-0.5 * (1 + (viscosity[:, :, i]/viscosity[:, :, j])**0.5 * (self.MW_list[species[j]]/self.MW_list[species[i]])**0.25)**2
                phi[:, :, nspecies*i + j] = (1+ (viscosity[:, :, i]/viscosity[:, :, j]*(self.MW_list[species[j]]/self.MW_list[species[i]])**0.5)**0.5)**2/(8**0.5 * (1+self.MW_list[species[i]]/self.MW_list[species[j]])**0.5)
                
        #apply mixing rules
        denominator_k = 0
        for i in  range(nspecies):
            denominator = 0
            for j in range(nspecies):
                denominator = denominator + molfractions[species[j]]*phi[:, :, nspecies*i + j]
            viscosity_mixture = viscosity_mixture + molfractions[species[i]]*viscosity[:, :, i]/denominator
            denominator_k = denominator_k + molfractions[species[i]]/ki[:, :, i]
            #k_mixture = k_mixture + molfractions[species[i]]*ki[:, :, i]/denominator
            k_mixture = k_mixture + 0.5*(molfractions[species[i]]*ki[:, :, i])
        k_mixture = k_mixture + 0.5/denominator_k
        return viscosity_mixture, k_mixture
    
    def unwrap_T(self, Tvector):
        """
        Used to manipulate vector of reactant and utility temperatures profiles
        into two arrays. Manipulates data into easily iterable form after 
        passing through the 1-dimensional ODE solver.
        
        Parameters
        ----------
        T_vector : List
            Temperature profile produced by ODE solver, units of K.
            
        Returns
        -------
        initial_reactant_Temps : Array
            2-Dimensional reactant temperature profile. Units of K.
        initial_utility_Temps : Array
            2-Dimensional utility temperature profile. Units of K.
        initial_fuel_Temps : Array
            2-Dimensional fuel temperature profile. Units of K.
        initial_reactantPlate_Temps : Array
            2-Dimensional reactant plate temperature profile. Units of K.
        initial_utilityPlate_Temps : Array
            2-Dimensional utility plate temperature profile. Units of K.
        initial_fuelPlate_Temps : Array
            2-Dimensional fuel plate temperature profile. Units of K.
        """
        initial_utility1_Temps = Tvector[0:self.rows*self.columns].reshape(self.rows, self.columns)
        initial_reactant2_Temps = Tvector[self.rows*self.columns:2*self.rows*self.columns].reshape(self.rows, self.columns)
        initial_fuel3_Temps = Tvector[2*self.rows*self.columns:3*self.rows*self.columns].reshape(self.rows, self.columns)
        initial_reactant4_Temps = Tvector[3*self.rows*self.columns:4*self.rows*self.columns].reshape(self.rows, self.columns)
        initial_utility5_Temps = Tvector[4*self.rows*self.columns:5*self.rows*self.columns].reshape(self.rows, self.columns)
        initial_utilityPlate1_Temps = Tvector[5*self.rows*self.columns:6*self.rows*self.columns].reshape(self.rows, self.columns)
        initial_reactantPlate2_Temps = Tvector[6*self.rows*self.columns:7*self.rows*self.columns].reshape(self.rows, self.columns)
        initial_fuelPlate3_Temps = Tvector[7*self.rows*self.columns:8*self.rows*self.columns].reshape(self.rows, self.columns)
        initial_reactantPlate4_Temps = Tvector[8*self.rows*self.columns:9*self.rows*self.columns].reshape(self.rows, self.columns)
        initial_utilityPlate5_Temps = Tvector[9*self.rows*self.columns:10*self.rows*self.columns].reshape(self.rows, self.columns)

        
        # initial_reactant_Temps = Tvector[0:self.rows*self.columns].reshape(self.rows, self.columns)
        # initial_utility_Temps = Tvector[self.rows*self.columns:self.rows*self.columns*2].reshape(self.rows, self.columns)
        # initial_reactantPlate_Temps = Tvector[self.rows*self.columns*2:self.rows*self.columns*3].reshape(self.rows, self.columns)
        # initial_utilityPlate_Temps = Tvector[self.rows*self.columns*3:self.rows*self.columns*4].reshape(self.rows, self.columns)
        
        #return initial_reactant_Temps, initial_utility_Temps, initial_reactantPlate_Temps, initial_utilityPlate_Temps
        return initial_utility1_Temps, initial_reactant2_Temps, initial_fuel3_Temps, \
            initial_reactant4_Temps, initial_utility5_Temps, initial_utilityPlate1_Temps, \
            initial_reactantPlate2_Temps, initial_fuelPlate3_Temps, initial_reactantPlate4_Temps, \
            initial_utilityPlate5_Temps
    
    def intraplate_cond(self, plate):
        """
        #######################################################################
        THIS SECTION NEEDS VALIDATION OF RESULTS/IS GIVING ABNORMAL RESULTS
        #######################################################################
        
        Offset the temperature in the x/z axis to handle conduction within plates.
        Uses numpy's roll with the first/last row or column as an insulated boundary.
        
         Parameters
        ----------
        plate : string
            String consisting of either 'reactant', 'utility', or 'fuel' for the
            selection of a plate.
            
        Returns
        -------
        Qnet : Array
            Net heat transfer in/out of each cell in the plate
        """
        
        if plate == 'reactant2':
            temps = self.reactantPlate2_T
        elif plate == 'utility1':
            temps = self.utilityPlate1_T
        elif plate == 'fuel3':
            temps = self.fuelPlate3_T
        elif plate == 'reactant4':
            temps = self.reactantPlate4_T
        elif plate == 'utility5':
            temps = self.utilityPlate5_T
        else:
            print('Incorrect plate selected for conduction terms!!')    

        offset_x_fwd = np.roll(temps, 1, 1)
        offset_x_rev = np.roll(temps, -1, 1)
        offset_z_fwd = np.roll(temps, 1, 0)
        offset_z_rev = np.roll(temps, -1, 0)
        
        temp_x_dir = (offset_x_rev - 2*temps + offset_x_fwd)/(self.deltax**2)
        temp_x_dir[:, 0] = 2*(temps[:, 1] - temps[:, 0])/(self.deltax**2)
        temp_x_dir[:, -1] = 2*(temps[:, -2] - temps[:, -1])/(self.deltax**2)
        
        temp_z_dir = (offset_z_rev - 2*temps + offset_z_fwd)/(self.deltaz**2)
        temp_z_dir[0, :] = 2*(temps[1, :] - temps[0, :])/(self.deltaz**2)
        temp_z_dir[-1, :] = 2*(temps[-2, :] - temps[-1, :])/(self.deltaz**2)
                
        dTdtNet = (temp_x_dir + temp_z_dir)*(self.metalk/(self.metalrho*self.metalcp))
        return dTdtNet
    
    def advective_transfer(self, fluid):
        """
        Determine the advective heat transfer terms

        Parameters
        ----------
        fluid : String
            String containing 'reactant', 'utility', or 'fuel' to set the 
            direction and temperature profile for heat transfer.

        Returns
        -------
        deltaT : Array
            Array of differential temperature terms to add to transient solver

        """
        
        if fluid == 'reactant2':
            temps = self.reactant2_T
            roll_dir = 1
            T0 = self.reactant[2]
        elif fluid == 'reactant4':
            temps = self.reactant4_T
            roll_dir = 1
            T0 = self.reactant[2]
        elif fluid == 'fuel3':
            temps = self.fuel3_T
            roll_dir = 1
            T0 = self.fuel[2]
        elif fluid == 'utility1':
            temps = self.utility1_T
            roll_dir = 0
            T0 = self.utility[2]
        elif fluid == 'utility5':
            temps = self.utility5_T
            roll_dir = 0
            T0 = self.utility[2]
            
        else: 
            print('Incorrect fluid selected for advective term!!')
        
        #offset temperature to get upstream temperature in each location
        offset_T = np.roll(temps, 1, roll_dir)
        deltaT = offset_T - temps
        
        
        #add boundary condition
        if roll_dir == 0:
            deltaT[0, :] = T0 - temps[0, :]
        elif roll_dir == 1:
            deltaT[:, 0] = T0 - temps[:, 0]
            
        return deltaT
    
    def update_pressures(self):
        """
        Update the pressure profile through the heat exchanger with Bernoulli's
        equation. D_h = square root of cross-sectional area
        
        Parameters
        -------
        None - pulled from class.

        Returns
        -------
        None - stored in class.

        """
        
        #calculate losses via Bernoulli's equation
        deltaP_utility1 = 2*self.utility1_f*self.deltaz/self.utility_dh*self.utility1_u**2*self.utility1_rho
        deltaP_reactant2 = 2*self.reactant2_f*self.deltax/self.reactant_dh*self.reactant2_u**2*self.reactant2_rho
        deltaP_fuel3 = 2*self.fuel3_f*self.deltax/self.fuel_dh*self.fuel3_u**2*self.fuel3_rho
        deltaP_reactant4 = 2*self.reactant4_f*self.deltax/self.reactant_dh*self.reactant4_u**2*self.reactant4_rho
        deltaP_utility5 = 2*self.utility5_f*self.deltaz/self.utility_dh*self.utility5_u**2*self.utility5_rho
        #print(deltaP_reactant)
    
        #if the array is unchanged from its initial state, then initialize
        if self.reactant2_P.mean() == self.reactant2_P[0, 0]:
            self.utility1_P[0, :] = self.utility[3] - deltaP_utility1[0, :]
            self.reactant2_P[:, 0] = self.reactant[3] - deltaP_reactant2[:, 0]
            self.fuel3_P[:, 0] = self.fuel[3] - deltaP_fuel3[:, 0]
            self.reactant4_P[:, 0] = self.reactant[3] - deltaP_reactant4[:, 0]
            self.utility5_P[0, :] = self.utility[3] - deltaP_utility5[0, :]
            
            for i in range(1, self.columns):
                self.reactant2_P[:, i] = self.reactant2_P[:, i-1] - deltaP_reactant2[:, i]
                self.reactant4_P[:, i] = self.reactant4_P[:, i-1] - deltaP_reactant4[:, i]
                self.fuel3_P[:, i] = self.fuel3_P[:, i-1] - deltaP_fuel3[:, i]

            for i in range(1, self.rows):
                self.utility1_P[i, :] = self.utility1_P[i-1, :] - deltaP_utility1[i, :]
                self.utility5_P[i, :] = self.utility5_P[i-1, :] - deltaP_utility5[i, :]
            
        #if the pressure drop has been initialized before, then update it with the new delta P    
        else:
            self.utility1_P = np.roll(self.utility1_P, 1, 0) - deltaP_utility1
            self.utility1_P[:, 0] = self.utility[3] - deltaP_utility1[0, :]
            self.reactant2_P = np.roll(self.reactant2_P, 1, 1) - deltaP_reactant2
            self.reactant2_P[0, :] = self.reactant[3] - deltaP_reactant2[:, 0]
            self.fuel3_P = np.roll(self.fuel3_P, 1, 1) - deltaP_fuel3
            self.fuel3_P[0, :] = self.reactant[3] - deltaP_fuel3[:, 0]
            self.reactant4_P = np.roll(self.reactant4_P, 1, 1) - deltaP_reactant4
            self.reactant4_P[0, :] = self.reactant[3] - deltaP_reactant4[:, 0]
            self.utility5_P = np.roll(self.utility5_P, 1, 0) - deltaP_utility5
            self.utility5_P[:, 0] = self.utility[3] - deltaP_utility5[0, :]
    
        return
    
    def transient_solver(self, t, T):
        """
        Method to model the transient temperature response of the PCHE. 
        Requires a 1-dimensional input.

        Parameters
        ----------
        t : Float
            Time points, units of s
        T : List (floats)
            Temperature profiles for the reactant and utility channels, units of K.
            Produced by concatenating lists of temperatures produced with the 
            ravel method. 
            
            E.g. np.concatenate([reactantinitials.ravel(), utilityinitials.ravel()])

        Returns
        -------
        dTdt : List (floats)
            Differenital temperature profile, for use in an ODE solver. Units
            of K s-1.

        """
        
        #start with extracting the initial temperature profile, setting dTdt to 0.
        self.utility1_T, self.reactant2_T, self.fuel3_T, self.reactant4_T, self.utility5_T, \
            self.utilityPlate1_T, self.reactantPlate2_T, self.fuelPlate3_T, \
            self.reactantPlate4_T, self.utilityPlate5_T = self.unwrap_T(T)
        
        dTdt_utility1, dTdt_reactant2, dTdt_fuel3, dTdt_reactant4, dTdt_utility5, \
            dTdt_utilityPlate1, dTdt_reactantPlate2, dTdt_fuelPlate3, \
            dTdt_reactantPlate_4, dTdt_utilityPlate5_T = map(np.copy, [np.zeros((self.rows, self.columns))]*10)
 
        self.mol_frac_and_cp()
        #print(self.utility_T)

        
        #update properties for the class
        self.utility1_mu, self.utility1_k = self.properties('utility1')
        self.reactant2_mu, self.reactant2_k = self.properties('reactant2')
        self.fuel3_mu, self.fuel3_k = self.properties('fuel3')
        self.reactant4_mu, self.reactant4_k = self.properties('reactant4')
        self.utility5_mu, self.utility5_k = self.properties('utility5')
        
        #calculate bulk velocity in channels
        self.utility1_u = self.utility[1]/(self.utility1_rho*self.dimensions[3]*self.utility_cs)
        self.reactant2_u = self.reactant[1]/(self.reactant2_rho*self.dimensions[2]*self.reactant_cs)
        self.fuel3_u = self.fuel[1]/(self.fuel3_rho*self.dimensions[2]*self.fuel_cs)
        self.reactant4_u = self.reactant[1]/(self.reactant4_rho*self.dimensions[2]*self.reactant_cs)
        self.utility5_u = self.utility[1]/(self.utility5_rho*self.dimensions[3]*self.utility_cs)

        #update Prandtl number, Reynolds number
        self.utility1_Pr = self.utility1_mu*self.utility1_cp/self.utility1_k
        self.reactant2_Pr = self.reactant2_mu*self.reactant2_cp/self.reactant2_k
        self.fuel3_Pr = self.fuel3_mu*self.fuel3_cp/self.fuel3_k
        self.reactant4_Pr = self.reactant4_mu*self.reactant4_cp/self.reactant4_k
        self.utility5_Pr = self.utility5_mu*self.utility5_cp/self.utility5_k
        
        self.utility1_Re = self.utility1_rho*self.utility1_u*self.utility_dh/self.utility1_mu
        self.reactant2_Re = self.reactant2_rho*self.reactant2_u*self.reactant_dh/self.reactant2_mu
        self.fuel3_Re = self.fuel3_rho*self.fuel3_u*self.fuel_dh/self.fuel3_mu
        self.reactant4_Re = self.reactant4_rho*self.reactant4_u*self.reactant_dh/self.reactant4_mu
        self.utility5_Re = self.utility5_rho*self.utility5_u*self.utility_dh/self.utility5_mu
                   
        #update friction factors
        self.utility1_f, self.utility1_Nu = self.ff_Nu('utility1')
        self.reactant2_f, self.reactant2_Nu = self.ff_Nu('reactant2')
        self.fuel3_f, self.fuel3_Nu = self.ff_Nu('fuel3')
        self.reactant4_f, self.reactant4_Nu = self.ff_Nu('reactant4')
        self.utility5_f, self.utility5_Nu = self.ff_Nu('utility5')
        
        #calculate convective heat transfer coefficients
        self.utility1_h = self.utility1_Nu*self.utility1_k/self.utility_dh   
        self.reactant2_h = self.reactant2_Nu*self.reactant2_k/self.reactant_dh     
        self.fuel3_h = self.fuel3_Nu*self.fuel3_k/self.fuel_dh     
        self.reactant4_h = self.reactant4_Nu*self.reactant4_k/self.reactant_dh     
        self.utility5_h = self.utility5_Nu*self.utility5_k/self.utility_dh     


        #calculate heat transfer between fluids and plates
        #positive value = heat gained by CV
        #negative value= heat lost by CV
        self.Q_utility1_fluid = self.utility1_h*(self.hx_area_1*(self.utilityPlate5_T - self.utility1_T) + self.hx_area_3*(self.utilityPlate1_T - self.utility1_T))
        self.Q_reactant2_fluid = self.reactant2_h*(self.hx_area_4*(self.utilityPlate1_T - self.reactant2_T) + self.hx_area_6*(self.reactantPlate2_T - self.reactant2_T))
        self.Q_fuel3_fluid = self.fuel3_h*(self.hx_area_4*(self.reactantPlate2_T - self.fuel3_T) + self.hx_area_6*(self.fuelPlate3_T - self.fuel3_T))
        self.Q_reactant4_fluid = self.reactant4_h*(self.hx_area_4*(self.fuelPlate3_T - self.reactant4_T) + self.hx_area_6*(self.reactantPlate4_T - self.reactant4_T))
        self.Q_utility5_fluid = self.utility5_h*(self.hx_area_1*(self.reactantPlate4_T - self.utility5_T) + self.hx_area_5*(self.utilityPlate5_T - self.utility5_T))
        
        self.Q_utilityPlate1 = self.utility1_h*self.hx_area_3*(self.utility1_T- self.utilityPlate1_T) + self.reactant2_h*self.hx_area_4*(self.reactant2_T - self.utilityPlate1_T)
        self.Q_reactantPlate2 = self.reactant2_h*self.hx_area_6*(self.reactant2_T - self.reactantPlate2_T) + self.fuel3_h*self.hx_area_4*(self.fuel3_T - self.reactantPlate2_T)
        self.Q_fuelPlate3 = self.fuel3_h*self.hx_area_6*(self.fuel3_T - self.fuelPlate3_T) + self.reactant4_h*self.hx_area_4*(self.reactant4_T - self.fuelPlate3_T)
        self.Q_reactantPlate4 = self.reactant4_h*self.hx_area_6*(self.reactant4_T - self.reactantPlate4_T) + self.utility5_h*self.hx_area_1*(self.utility5_T - self.reactantPlate4_T)
        self.Q_utilityPlate5 = self.utility5_h*self.hx_area_1*(self.utility5_T - self.utilityPlate5_T) + self.utility1_h*self.hx_area_1*(self.utility1_T - self.utilityPlate5_T)
        
        #add conduction between plates (interplate/y-dir)
        self.Q_utilityPlate1 = self.Q_utilityPlate1 + self.metalk*(self.hx_area_2*(self.utilityPlate5_T - self.utilityPlate1_T) + self.hx_area_5*(self.reactantPlate2_T - self.utilityPlate1_T))
        self.Q_reactantPlate2 = self.Q_reactantPlate2 + self.metalk*self.hx_area_5*(self.fuelPlate3_T + self.utilityPlate1_T - 2*self.reactantPlate2_T)
        self.Q_fuelPlate3 = self.Q_fuelPlate3 + self.metalk*self.hx_area_5*(self.reactantPlate2_T + self.reactantPlate4_T - 2*self.fuelPlate3_T)
        self.Q_reactantPlate4 = self. Q_reactantPlate4 + self.metalk*(self.hx_area_5*(self.fuelPlate3_T - self.reactantPlate4_T) + self.hx_area_2*(self.utilityPlate5_T - self.reactantPlate4_T))
        self.Q_utilityPlate5 = self.Q_utilityPlate5 + self.metalk*(self.hx_area_5*(self.reactantPlate4_T + self.utilityPlate1_T - 2*self.utilityPlate5_T))
        
        #convert from heat transfer to dT, neglective advective term
        dTdt_utility1 = self.Q_utility1_fluid/(self.utility1_rho*self.utility_Vcell*self.utility1_cp)
        dTdt_reactant2 = self.Q_reactant2_fluid/(self.reactant2_rho*self.reactant_Vcell*self.reactant2_cp)
        dTdt_fuel3 = self.Q_fuel3_fluid/(self.fuel3_rho*self.fuel_Vcell*self.fuel3_cp)
        dTdt_reactant4 = self.Q_reactant4_fluid/(self.reactant4_rho*self.reactant_Vcell*self.reactant4_cp)
        dTdt_utility5 = self.Q_utility5_fluid/(self.utility5_rho*self.utility_Vcell*self.utility5_cp)
        
        dTdt_utilityPlate1 = self.Q_utilityPlate1/(self.metalrho*self.utilityPlate_Vcell*self.metalcp)
        dTdt_reactantPlate2 = self.Q_reactantPlate2/(self.metalrho*self.reactantPlate_Vcell*self.metalcp)
        dTdt_fuelPlate3 = self.Q_fuelPlate3/(self.metalrho*self.fuelPlate_Vcell*self.metalcp)
        dTdt_reactantPlate4 = self.Q_reactantPlate4/(self.metalrho*self.reactantPlate_Vcell*self.metalcp)
        dTdt_utilityPlate5 = self.Q_utilityPlate5/(self.metalrho*self.utilityPlate_Vcell*self.metalcp)

     
        #add the advective term to dTdt
        dTdt_utility1 = dTdt_utility1 + self.utility1_u*self.advective_transfer('utility1')/self.deltaz
        dTdt_reactant2 = dTdt_reactant2 + self.reactant2_u*self.advective_transfer('reactant2')/self.deltax
        dTdt_fuel3 = dTdt_fuel3 + self.fuel3_u*self.advective_transfer('fuel3')/self.deltax
        dTdt_reactant4 = dTdt_reactant4 + self.reactant4_u*self.advective_transfer('reactant4')/self.deltax
        dTdt_utility5 = dTdt_utility5 + self.utility5_u*self.advective_transfer('utility5')/self.deltaz
        
        #advective_reactant = self.reactant_u*self.advective_transfer('reactant')/self.deltax
        #advective_utility = self.utility_u*self.advective_transfer('utility')/self.deltaz        
        #dTdt_reactant = dTdt_reactant + advective_reactant
        #dTdt_utility = dTdt_utility + advective_utility
        
        dTdt_utilityPlate1 = dTdt_utilityPlate1 + self.intraplate_cond('utility1')
        dTdt_reactantPlate2 = dTdt_reactantPlate2 + self.intraplate_cond('reactant2')
        dTdt_fuelPlate3 = dTdt_fuelPlate3 + self.intraplate_cond('fuel3')
        dTdt_reactantPlate4 = dTdt_reactantPlate4 + self.intraplate_cond('reactant4')
        dTdt_utilityPlate5 = dTdt_utilityPlate5 + self.intraplate_cond('utility5')

        
        #dTdt_reactantPlate = dTdt_reactantPlate + self.intraplate_cond('reactant')
        #dTdt_utilityPlate = dTdt_utilityPlate + self.intraplate_cond('utility')
        
        #wrap up dT/dt as a vector for use in solve i
        #dTdt = np.concatenate([dTdt_reactant.ravel(), dTdt_utility.ravel(), 
        #                       dTdt_reactantPlate.ravel(), dTdt_utilityPlate.ravel()])
        #self.update_pressures()
        
        dTdt = np.concatenate([dTdt_utility1.ravel(), dTdt_reactant2.ravel(), dTdt_fuel3.ravel(), 
                               dTdt_reactant4.ravel(), dTdt_utility5.ravel(), dTdt_utilityPlate1.ravel(),
                               dTdt_reactantPlate2.ravel(), dTdt_fuelPlate3.ravel(), dTdt_reactantPlate4.ravel(), 
                               dTdt_utilityPlate5.ravel()])
        
        return dTdt
    
    def steady_solver(self, initialTemps):
        dTdt = self.transient_solver(0, initialTemps)
        #dTdt = (dTdt**2).sum()**0.5 #comment out for fsolve
        #print(dTdt)
        return dTdt
        
###############################################################################
###############################################################################    

def convert_T_vector(T_vector, dims):
    utility1Temps = T_vector[0:dims[2]*dims[3]].reshape(dims[2], dims[3])
    reactant2Temps = T_vector[dims[2]*dims[3]:2*dims[2]*dims[3]].reshape(dims[2], dims[3])
    fuel3Temps = T_vector[2*dims[2]*dims[3]:3*dims[2]*dims[3]].reshape(dims[2], dims[3])
    reactant4Temps = T_vector[3*dims[2]*dims[3]:4*dims[2]*dims[3]].reshape(dims[2], dims[3])
    utility5Temps = T_vector[4*dims[2]*dims[3]:5*dims[2]*dims[3]].reshape(dims[2], dims[3])
    
    utilityPlate1 = T_vector[5*dims[2]*dims[3]:6*dims[2]*dims[3]].reshape(dims[2], dims[3])
    reactantPlate2 = T_vector[6*dims[2]*dims[3]:7*dims[2]*dims[3]].reshape(dims[2], dims[3])
    fuelPlate3 = T_vector[7*dims[2]*dims[3]:8*dims[2]*dims[3]].reshape(dims[2], dims[3])
    reactantPlate4 = T_vector[8*dims[2]*dims[3]:9*dims[2]*dims[3]].reshape(dims[2], dims[3])
    utilityPlate5 = T_vector[9*dims[2]*dims[3]:10*dims[2]*dims[3]].reshape(dims[2], dims[3])
    return utility1Temps, reactant2Temps, fuel3Temps, reactant4Temps, utility5Temps,\
        utilityPlate1, reactantPlate2, fuelPlate3, reactantPlate4, utilityPlate5


reactant_inlet = [{'CO2':1}, 0.00702/5, 900, 101325]
utility_inlet = [{'CO2':1}, 0.005, 700, 101325]
fuel_inlet = [{'CH4':1}, 0.0001, 500, 101325]
dimensions = [0.0015, 0.0015, 10, 10, 0.0011, 0.0021]

exchanger = crossflow_PCHE(reactant_inlet, utility_inlet, fuel_inlet, dimensions)

initial_T_reactant = reactant_inlet[2]*np.ones((dimensions[2], dimensions[3]))
initial_T_reactantPlate = reactant_inlet[2]*np.ones((dimensions[2], dimensions[3]))
initial_T_utility = utility_inlet[2]*np.ones((dimensions[2], dimensions[3]))
initial_T_utilityPlate = utility_inlet[2]*np.ones((dimensions[2], dimensions[3]))
initial_T_fuel = fuel_inlet[2]*np.ones((dimensions[2], dimensions[3]))
initial_T_fuelPlate = fuel_inlet[2]*np.ones((dimensions[2], dimensions[3]))


initial_temps = np.concatenate([initial_T_utility.ravel(), initial_T_reactant.ravel(), initial_T_fuel.ravel(), initial_T_reactant.ravel(), initial_T_utility.ravel(),
                                initial_T_utilityPlate.ravel(), initial_T_reactantPlate.ravel(), initial_T_fuelPlate.ravel(), initial_T_reactantPlate.ravel(), initial_T_utilityPlate.ravel()])
    

t0 = time.time()
solution = solve_ivp(exchanger.transient_solver, [0, 10000], initial_temps, method = 'BDF', t_eval = [0, 1, 10, 100, 1000, 10000])

for i in range(10):
    solution = solve_ivp(exchanger.transient_solver, [0, 10000], solution['y'][:, -1], method = 'BDF', t_eval = [0, 1, 10, 100, 1000, 10000])
    exchanger.update_pressures()
tend = time.time()

print('time to solve to steady-state with BDF @ 10 iterations:', tend-t0, 's')


T_utility1, T_reactant2, T_fuel3, T_reactant4, T_utility5, T_utilityPlate1, T_reactantPlate2, T_fuelPlate3, T_reactantPlate4, T_utilityPlate5 = convert_T_vector(solution['y'][:, -1], dimensions)
# T_reactant, T_utility, T_reactant_plate, T_utility_plate = convert_T_vector(solution['y'][:, -1], dimensions)
# P_reactant = exchanger.reactant_P.min()
# P_utility = exchanger.utility_P.min()


# results = np.zeros(100)
# for i in range(400, 1500, 25):
#      reactant_inlet = [{'H2O':1}, 0.00702/5, i, 101325]
#      utility_inlet = [{'H2O':1}, 0.00702/5, i, 101325]
#      exchanger = crossflow_PCHE(reactant_inlet, utility_inlet, dimensions)
#      solution = solve_ivp(exchanger.transient_solver, [0, 10000], initial_temps, method = 'BDF', t_eval = [0, 1, 10, 100, 1000, 10000])
#      results[int((i-400)/25)] = exchanger.reactant_mu[1, 1]


