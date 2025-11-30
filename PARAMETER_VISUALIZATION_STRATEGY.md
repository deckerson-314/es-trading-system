# Parameter Visualization Strategy

## Overview

Understanding how parameters evolve, their effects on metrics, and their sensitivity is crucial for:
1. **Identifying important parameters** - Which ones actually matter?
2. **Understanding convergence** - Are parameters stabilizing or still exploring?
3. **Detecting overfitting** - Are parameters converging to extreme values?
4. **Optimizing ranges** - Are we using the full parameter space or stuck in corners?
5. **Finding interactions** - Do parameters work together or independently?

## Current Visualizations

### What We Have Now:
1. **Parameter Evolution Plots** (`ga_diagnostics_v3/param_evolution/`)
   - Shows how each parameter changes in the best solution over generations
   - Simple line plots: parameter value vs generation
   - **Limitation**: Only shows best solution, not population distribution

2. **Convergence Plots** (in HTML dashboard)
   - Shows fitness metrics converging over generations
   - **Limitation**: Doesn't show which parameters drive the convergence

3. **Pareto Front 3D** (in HTML dashboard)
   - Shows trade-offs between objectives
   - **Limitation**: Doesn't show parameter values

## Proposed Visualizations

### 1. Parameter Convergence Analysis

**Goal**: Understand how parameters evolve over generations

**Visualizations**:
- **Parameter vs Generation**: Line plots showing parameter value over generations
  - Best solution (line)
  - Population mean (dashed line)
  - Population std dev (shaded area)
  - Shows if parameters are converging or still exploring

- **Parameter Distribution Over Generations**: Histograms/box plots
  - Shows how parameter distributions change
  - Identifies if GA is exploring or converging
  - Detects if parameters are stuck at boundaries

**Implementation**: Track parameter values in logbook for each generation

### 2. Parameter Effects on Metrics

**Goal**: Understand which parameters affect which metrics

**Visualizations**:
- **Correlation Heatmap**: Parameter × Metric correlation matrix
  - Shows which parameters correlate with Sortino, Drawdown, PF, etc.
  - Color-coded: red = negative, blue = positive
  - Identifies key parameters for each metric

- **Parameter vs Metric Scatter Plots**: 
  - Each point = one solution
  - X-axis = parameter value
  - Y-axis = metric value (e.g., Sortino)
  - Color = another metric (e.g., trades/day)
  - Shows relationships and interactions

- **Top/Bottom Comparison**: 
  - Compare parameter values in top 25% vs bottom 25% solutions
  - Identifies which parameters distinguish good from bad solutions

**Implementation**: Extract parameter values from Hall of Fame, calculate correlations

### 3. Sensitivity Analysis

**Goal**: Identify which parameters are most important

**Methods**:
1. **Correlation with Fitness**: How strongly does parameter correlate with Sortino?
2. **Top-Bottom Difference**: How different are parameter values in top vs bottom solutions?
3. **Range Utilization**: How much of the allowed range is actually used?
4. **Variability**: How much does the parameter vary across solutions?

**Visualizations**:
- **Tornado Plot**: Bar chart showing parameter importance scores
  - Tallest bars = most important parameters
  - Helps focus optimization on what matters

- **Sensitivity Table**: CSV with all metrics for each parameter
  - Sortable by importance
  - Exportable for further analysis

**Implementation**: Calculate multiple importance metrics, combine into single score

### 4. Parameter Interactions

**Goal**: Understand how parameters work together

**Visualizations**:
- **2D Parameter Scatter Plots**: 
  - X-axis = Parameter A
  - Y-axis = Parameter B
  - Color = Sortino (or other metric)
  - Shows if parameters interact (e.g., both need to be high/low together)

- **3D Parameter Space**: 
  - Interactive 3D plot with top 3 parameters
  - Color = fitness
  - Identifies optimal regions in parameter space

**Implementation**: Plot top parameter pairs, use color coding for fitness

### 5. Parameter Distribution Analysis

**Goal**: Understand parameter distributions in good vs bad solutions

**Visualizations**:
- **Overlapping Histograms**: 
  - Top 25% solutions (green)
  - Bottom 25% solutions (red)
  - Shows if good solutions have different parameter distributions

- **Box Plots**: 
  - Compare parameter distributions across solution quality tiers
  - Shows medians, quartiles, outliers

**Implementation**: Split solutions by fitness, plot distributions

## Implementation Plan

### Phase 1: Basic Analysis (Current Script)
✅ Parameter vs Sortino scatter plots
✅ Correlation heatmap
✅ Sensitivity analysis (importance scores)
✅ Parameter distributions (top vs bottom)
✅ Parameter interactions (2D scatter)

### Phase 2: Generation-by-Generation Tracking
- Track parameter values in logbook for each generation
- Create convergence plots showing parameter evolution
- Show population statistics (mean, std dev) over generations

### Phase 3: Interactive Dashboard
- Add parameter analysis section to HTML dashboard
- Interactive plots with hover details
- Filter by solution quality
- Compare different parameter combinations

### Phase 4: Advanced Analysis
- Principal Component Analysis (PCA) to find parameter combinations
- Clustering to identify parameter "types" of solutions
- Machine learning to predict fitness from parameters

## Usage

### Run Analysis:
```bash
python visualize_parameter_analysis.py
```

### Output Files:
- `ga_diagnostics_v3/parameter_analysis/parameter_convergence_vs_sortino.html`
- `ga_diagnostics_v3/parameter_analysis/parameter_metric_correlation.html`
- `ga_diagnostics_v3/parameter_analysis/parameter_importance_tornado.html`
- `ga_diagnostics_v3/parameter_analysis/parameter_distributions.html`
- `ga_diagnostics_v3/parameter_analysis/parameter_interactions.html`
- `ga_diagnostics_v3/parameter_analysis/parameter_metric_correlation.csv`
- `ga_diagnostics_v3/parameter_analysis/parameter_sensitivity_analysis.csv`

## Key Insights to Look For

1. **Convergence**: Are parameters stabilizing or still exploring?
   - If still exploring: Need more generations
   - If converged: May have found optimal region

2. **Boundary Sticking**: Are parameters at min/max values?
   - If yes: Parameter range may be too narrow
   - Consider expanding range

3. **Low Importance Parameters**: Parameters with low importance scores
   - May not matter for optimization
   - Could be fixed to reduce search space

4. **High Correlation**: Parameters that strongly correlate with fitness
   - These are the key parameters
   - Focus optimization on these

5. **Interactions**: Parameters that work together
   - May need to optimize together
   - Could indicate strategy logic dependencies

## Next Steps

1. Run the visualization script on current GA results
2. Review the generated plots
3. Identify key parameters and their effects
4. Adjust parameter ranges if needed
5. Consider fixing low-importance parameters
6. Focus optimization on high-importance parameters

