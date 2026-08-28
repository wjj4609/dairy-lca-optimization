#!/usr/bin/env Rscript

# Generic fresh-feed ration optimization using external CSV inputs.
# Percentage-scale inputs are converted to proportions before model construction.

OBJECTIVE_NAMES <- c("GHG", "NFP", "Cost")
OBJECTIVE_WEIGHTS <- c(GHG = 1 / 3, NFP = 1 / 3, Cost = 1 / 3)
TOL <- 1e-8
FEASIBILITY_TOL <- 1e-6
SYNTHETIC_WARNING <- paste(
  "SYNTHETIC DEMONSTRATION ONLY - NOT FOR RESEARCH USE OR",
  "SCIENTIFIC INTERPRETATION."
)

usage_text <- paste0(
  "Usage:\n",
  "  Rscript workflows/optimize_diet.R --example\n",
  "  Rscript workflows/optimize_diet.R \\\n",
  "    --feed FILE --constraints FILE \\\n",
  "    [--output-dir DIRECTORY]\n\n",
  "The example uses only the bundled synthetic CSV files.\n"
)

parse_cli <- function(args) {
  options <- list(
    example = FALSE,
    help = FALSE,
    feed = NULL,
    constraints = NULL,
    output_dir = NULL
  )

  i <- 1
  while (i <= length(args)) {
    argument <- args[[i]]
    if (argument == "--example") {
      options$example <- TRUE
      i <- i + 1
    } else if (argument %in% c("--help", "-h")) {
      options$help <- TRUE
      i <- i + 1
    } else if (argument %in% c("--feed", "--constraints", "--output-dir")) {
      if (i == length(args)) {
        stop("Missing value after ", argument, ".\n\n", usage_text, call. = FALSE)
      }
      key <- switch(
        argument,
        "--feed" = "feed",
        "--constraints" = "constraints",
        "--output-dir" = "output_dir"
      )
      options[[key]] <- args[[i + 1]]
      i <- i + 2
    } else {
      stop("Unknown argument: ", argument, "\n\n", usage_text, call. = FALSE)
    }
  }

  if (isTRUE(options$example) && any(!vapply(
    options[c("feed", "constraints")],
    is.null,
    logical(1)
  ))) {
    stop(
      "--example cannot be combined with custom input-file arguments.",
      call. = FALSE
    )
  }

  options
}

script_path <- function() {
  file_argument <- grep(
    "^--file=",
    commandArgs(trailingOnly = FALSE),
    value = TRUE
  )
  if (length(file_argument) == 0) {
    stop("Cannot determine the script location.", call. = FALSE)
  }
  path <- sub("^--file=", "", file_argument[[1]])
  if (!file.exists(path)) {
    stop("Cannot find the running script: ", path, call. = FALSE)
  }
  path
}

cli <- parse_cli(commandArgs(trailingOnly = TRUE))
if (isTRUE(cli$help)) {
  cat(usage_text)
  quit(save = "no", status = 0)
}

repository_root <- file.path(dirname(script_path()), "..")

if (isTRUE(cli$example)) {
  cli$feed <- file.path(
    repository_root,
    "examples",
    "synthetic_optimization_feed.csv"
  )
  cli$constraints <- file.path(
    repository_root,
    "examples",
    "synthetic_optimization_constraints.csv"
  )
  if (is.null(cli$output_dir)) {
    cli$output_dir <- file.path(
      repository_root,
      "outputs",
      "synthetic_optimization"
    )
  }
} else {
  missing_arguments <- names(Filter(
    is.null,
    cli[c("feed", "constraints")]
  ))
  if (length(missing_arguments) > 0) {
    stop(
      "Missing required input arguments: ",
      paste(paste0("--", missing_arguments), collapse = ", "),
      "\n\n",
      usage_text,
      call. = FALSE
    )
  }
  if (is.null(cli$output_dir)) {
    cli$output_dir <- file.path(
      repository_root,
      "outputs",
      "diet_optimization"
    )
  }
}

required_packages <- c("ompr", "ompr.roi", "ROI.plugin.glpk")
missing_packages <- required_packages[
  !vapply(required_packages, requireNamespace, logical(1), quietly = TRUE)
]
if (length(missing_packages) > 0) {
  stop(
    "Missing required R packages: ",
    paste(missing_packages, collapse = ", "),
    ". See docs/r_dependencies.md for installation instructions.",
    call. = FALSE
  )
}

suppressPackageStartupMessages({
  library(ompr)
  library(ompr.roi)
  library(ROI.plugin.glpk)
})

if (abs(sum(OBJECTIVE_WEIGHTS) - 1) > TOL ||
    !identical(names(OBJECTIVE_WEIGHTS), OBJECTIVE_NAMES)) {
  stop("The fixed equal-weight objective definition is invalid.", call. = FALSE)
}

feed_headers <- c(
  "synthetic",
  "feed_id",
  "feed_label",
  "dry_matter_proportion_pct",
  "net_energy_lactation_mj_per_kg_dm",
  "crude_protein_pct_dm",
  "ndf_pct_dm",
  "calcium_pct_dm",
  "phosphorus_pct_dm",
  "forage_indicator",
  "ghg_kg_co2e_per_kg_fresh_feed",
  "nfp_g_n_per_kg_fresh_feed",
  "cost_unit_per_t_fresh_feed",
  "warning"
)

constraint_headers <- c(
  "synthetic",
  "group_id",
  "stage_id",
  "dmi_min_kg_day",
  "dmi_max_kg_day",
  "nel_min_mj_per_kg_dm",
  "nel_max_mj_per_kg_dm",
  "crude_protein_min_pct_dm",
  "crude_protein_max_pct_dm",
  "ndf_min_pct_dm",
  "ndf_max_pct_dm",
  "calcium_min_pct_dm",
  "calcium_max_pct_dm",
  "phosphorus_min_pct_dm",
  "phosphorus_max_pct_dm",
  "forage_min_pct_dm",
  "forage_max_pct_dm",
  "warning"
)

read_public_csv <- function(file_path, expected_headers, label) {
  if (!file.exists(file_path)) {
    stop(label, " file does not exist: ", file_path, call. = FALSE)
  }
  data <- read.csv(
    file_path,
    header = TRUE,
    stringsAsFactors = FALSE,
    check.names = FALSE,
    na.strings = c("", "NA"),
    strip.white = TRUE,
    fileEncoding = "UTF-8"
  )
  if (!identical(names(data), expected_headers)) {
    stop(
      label,
      " headers must exactly match:\n",
      paste(expected_headers, collapse = ","),
      "\nFound:\n",
      paste(names(data), collapse = ","),
      call. = FALSE
    )
  }
  if (nrow(data) == 0) {
    stop(label, " must contain at least one data row.", call. = FALSE)
  }
  data
}

parse_boolean_column <- function(values, label) {
  parsed <- toupper(trimws(as.character(values)))
  if (anyNA(values) || any(!parsed %in% c("TRUE", "FALSE"))) {
    stop(label, " must contain only TRUE or FALSE.", call. = FALSE)
  }
  parsed == "TRUE"
}

coerce_numeric_columns <- function(data, columns, label) {
  for (column in columns) {
    converted <- suppressWarnings(as.numeric(data[[column]]))
    if (anyNA(converted) || any(!is.finite(converted))) {
      stop(
        label,
        " column '",
        column,
        "' must contain finite numeric values in every row.",
        call. = FALSE
      )
    }
    data[[column]] <- converted
  }
  data
}

validate_text <- function(values, label) {
  trimmed <- trimws(as.character(values))
  if (anyNA(values) || any(!nzchar(trimmed))) {
    stop(label, " must not contain blank values.", call. = FALSE)
  }
  trimmed
}

validate_ids <- function(values, label, unique_required = TRUE) {
  ids <- validate_text(values, label)
  if (any(grepl("[<>]", ids))) {
    stop(label, " contains an unreplaced placeholder.", call. = FALSE)
  }
  if (any(!grepl("^[A-Za-z0-9][A-Za-z0-9_.-]*$", ids))) {
    stop(
      label,
      " may contain only letters, numbers, period, underscore, and hyphen.",
      call. = FALSE
    )
  }
  if (isTRUE(unique_required) && anyDuplicated(ids)) {
    stop(label, " must be unique.", call. = FALSE)
  }
  ids
}

check_range <- function(values, lower, upper, label, lower_open = FALSE) {
  lower_failed <- if (isTRUE(lower_open)) values <= lower else values < lower
  if (any(lower_failed | values > upper)) {
    lower_symbol <- if (isTRUE(lower_open)) ">" else ">="
    stop(
      label,
      " must be ",
      lower_symbol,
      " ",
      lower,
      " and <= ",
      upper,
      ".",
      call. = FALSE
    )
  }
}

check_bound_pairs <- function(data, pairs, label) {
  for (pair in pairs) {
    if (any(data[[pair[[1]]]] > data[[pair[[2]]]])) {
      stop(
        label,
        " has a lower bound greater than its upper bound for ",
        pair[[1]],
        " / ",
        pair[[2]],
        ".",
        call. = FALSE
      )
    }
  }
}

validate_synthetic_warning <- function(data, label) {
  warnings <- toupper(as.character(data$warning))
  if (anyNA(data$warning) ||
      any(!grepl("SYNTHETIC DEMONSTRATION ONLY", warnings, fixed = TRUE)) ||
      any(!grepl("NOT FOR RESEARCH USE", warnings, fixed = TRUE))) {
    stop(
      label,
      " synthetic rows must carry the full synthetic-use warning.",
      call. = FALSE
    )
  }
}

feed_public <- read_public_csv(cli$feed, feed_headers, "Feed input")
constraint_public <- read_public_csv(
  cli$constraints,
  constraint_headers,
  "Constraint input"
)
feed_public$synthetic <- parse_boolean_column(
  feed_public$synthetic,
  "Feed input synthetic"
)
constraint_public$synthetic <- parse_boolean_column(
  constraint_public$synthetic,
  "Constraint input synthetic"
)
feed_numeric <- c(
  "dry_matter_proportion_pct",
  "net_energy_lactation_mj_per_kg_dm",
  "crude_protein_pct_dm",
  "ndf_pct_dm",
  "calcium_pct_dm",
  "phosphorus_pct_dm",
  "forage_indicator",
  "ghg_kg_co2e_per_kg_fresh_feed",
  "nfp_g_n_per_kg_fresh_feed",
  "cost_unit_per_t_fresh_feed"
)
constraint_numeric <- setdiff(
  constraint_headers,
  c("synthetic", "group_id", "stage_id", "warning")
)
feed_public <- coerce_numeric_columns(
  feed_public,
  feed_numeric,
  "Feed input"
)
constraint_public <- coerce_numeric_columns(
  constraint_public,
  constraint_numeric,
  "Constraint input"
)
feed_public$feed_id <- validate_ids(feed_public$feed_id, "Feed input feed_id")
feed_public$feed_label <- validate_text(
  feed_public$feed_label,
  "Feed input feed_label"
)
constraint_public$group_id <- validate_ids(
  constraint_public$group_id,
  "Constraint input group_id",
  unique_required = FALSE
)
constraint_public$stage_id <- validate_ids(
  constraint_public$stage_id,
  "Constraint input stage_id",
  unique_required = FALSE
)

group_stage_key <- paste(
  constraint_public$group_id,
  constraint_public$stage_id,
  sep = "::"
)
if (anyDuplicated(group_stage_key)) {
  stop("Each group_id / stage_id pair must be unique.", call. = FALSE)
}

check_range(
  feed_public$dry_matter_proportion_pct,
  0,
  100,
  "dry_matter_proportion_pct",
  lower_open = TRUE
)
check_range(
  feed_public$net_energy_lactation_mj_per_kg_dm,
  0,
  Inf,
  "net_energy_lactation_mj_per_kg_dm",
  lower_open = TRUE
)
for (column in c(
  "crude_protein_pct_dm",
  "ndf_pct_dm",
  "calcium_pct_dm",
  "phosphorus_pct_dm"
)) {
  check_range(feed_public[[column]], 0, 100, column)
}
if (any(!feed_public$forage_indicator %in% c(0, 1))) {
  stop("forage_indicator must contain only 0 or 1.", call. = FALSE)
}

if (any(constraint_public$dmi_min_kg_day <= 0)) {
  stop("dmi_min_kg_day must be greater than zero.", call. = FALSE)
}
check_range(
  constraint_public$nel_min_mj_per_kg_dm,
  0,
  Inf,
  "nel_min_mj_per_kg_dm"
)
check_range(
  constraint_public$nel_max_mj_per_kg_dm,
  0,
  Inf,
  "nel_max_mj_per_kg_dm"
)
for (column in c(
  "crude_protein_min_pct_dm",
  "crude_protein_max_pct_dm",
  "ndf_min_pct_dm",
  "ndf_max_pct_dm",
  "calcium_min_pct_dm",
  "calcium_max_pct_dm",
  "phosphorus_min_pct_dm",
  "phosphorus_max_pct_dm",
  "forage_min_pct_dm",
  "forage_max_pct_dm"
)) {
  check_range(constraint_public[[column]], 0, 100, column)
}
check_bound_pairs(
  constraint_public,
  list(
    c("dmi_min_kg_day", "dmi_max_kg_day"),
    c("nel_min_mj_per_kg_dm", "nel_max_mj_per_kg_dm"),
    c("crude_protein_min_pct_dm", "crude_protein_max_pct_dm"),
    c("ndf_min_pct_dm", "ndf_max_pct_dm"),
    c("calcium_min_pct_dm", "calcium_max_pct_dm"),
    c("phosphorus_min_pct_dm", "phosphorus_max_pct_dm"),
    c("forage_min_pct_dm", "forage_max_pct_dm")
  ),
  "Constraint input"
)

for (column in c(
  "ghg_kg_co2e_per_kg_fresh_feed",
  "nfp_g_n_per_kg_fresh_feed",
  "cost_unit_per_t_fresh_feed"
)) {
  if (any(feed_public[[column]] < 0)) {
    stop(column, " must be non-negative.", call. = FALSE)
  }
}

synthetic_flags <- c(
  feed_public$synthetic,
  constraint_public$synthetic
)
if (length(unique(synthetic_flags)) != 1) {
  stop(
    "All rows across the two input files must use the same synthetic flag.",
    call. = FALSE
  )
}
run_is_synthetic <- isTRUE(unique(synthetic_flags))

if (isTRUE(cli$example)) {
  if (!run_is_synthetic) {
    stop("The bundled example must be marked synthetic.", call. = FALSE)
  }
  validate_synthetic_warning(feed_public, "Feed input")
  validate_synthetic_warning(constraint_public, "Constraint input")
  id_values <- c(
    feed_public$feed_id,
    constraint_public$group_id,
    constraint_public$stage_id
  )
  if (any(!grepl("^synthetic_", id_values))) {
    stop("Every bundled example ID must begin with 'synthetic_'.", call. = FALSE)
  }
}

run_warning <- if (run_is_synthetic) SYNTHETIC_WARNING else ""

# Convert all public percentage-scale fields to internal proportions.
feed <- data.frame(
  feed_id = feed_public$feed_id,
  feed_label = feed_public$feed_label,
  DM = feed_public$dry_matter_proportion_pct / 100,
  NEL = feed_public$net_energy_lactation_mj_per_kg_dm,
  CP = feed_public$crude_protein_pct_dm / 100,
  NDF = feed_public$ndf_pct_dm / 100,
  Ca = feed_public$calcium_pct_dm / 100,
  P = feed_public$phosphorus_pct_dm / 100,
  forage = feed_public$forage_indicator,
  GHG = feed_public$ghg_kg_co2e_per_kg_fresh_feed,
  NFP = feed_public$nfp_g_n_per_kg_fresh_feed,
  price = feed_public$cost_unit_per_t_fresh_feed,
  stringsAsFactors = FALSE
)

constraints <- data.frame(
  group_id = constraint_public$group_id,
  stage_id = constraint_public$stage_id,
  DMI_min = constraint_public$dmi_min_kg_day,
  DMI_max = constraint_public$dmi_max_kg_day,
  NEL_min = constraint_public$nel_min_mj_per_kg_dm,
  NEL_max = constraint_public$nel_max_mj_per_kg_dm,
  CP_min = constraint_public$crude_protein_min_pct_dm / 100,
  CP_max = constraint_public$crude_protein_max_pct_dm / 100,
  NDF_min = constraint_public$ndf_min_pct_dm / 100,
  NDF_max = constraint_public$ndf_max_pct_dm / 100,
  Ca_min = constraint_public$calcium_min_pct_dm / 100,
  Ca_max = constraint_public$calcium_max_pct_dm / 100,
  P_min = constraint_public$phosphorus_min_pct_dm / 100,
  P_max = constraint_public$phosphorus_max_pct_dm / 100,
  forage_min = constraint_public$forage_min_pct_dm / 100,
  forage_max = constraint_public$forage_max_pct_dm / 100,
  stringsAsFactors = FALSE
)

# x[i] is fresh-feed intake in kg/day. Nutrient constraints are DM-weighted.
build_base_model <- function(feed, requirement) {
  n_feed <- nrow(feed)

  MIPModel() |>
    add_variable(x[i], i = 1:n_feed, type = "continuous", lb = 0) |>
    add_constraint(
      sum_over(x[i] * feed$DM[i], i = 1:n_feed) >= requirement$DMI_min
    ) |>
    add_constraint(
      sum_over(x[i] * feed$DM[i], i = 1:n_feed) <= requirement$DMI_max
    ) |>
    add_constraint(
      sum_over(
        x[i] * feed$DM[i] * (feed$NEL[i] - requirement$NEL_min),
        i = 1:n_feed
      ) >= 0
    ) |>
    add_constraint(
      sum_over(
        x[i] * feed$DM[i] * (feed$NEL[i] - requirement$NEL_max),
        i = 1:n_feed
      ) <= 0
    ) |>
    add_constraint(
      sum_over(
        x[i] * feed$DM[i] * (feed$CP[i] - requirement$CP_min),
        i = 1:n_feed
      ) >= 0
    ) |>
    add_constraint(
      sum_over(
        x[i] * feed$DM[i] * (feed$CP[i] - requirement$CP_max),
        i = 1:n_feed
      ) <= 0
    ) |>
    add_constraint(
      sum_over(
        x[i] * feed$DM[i] * (feed$NDF[i] - requirement$NDF_min),
        i = 1:n_feed
      ) >= 0
    ) |>
    add_constraint(
      sum_over(
        x[i] * feed$DM[i] * (feed$NDF[i] - requirement$NDF_max),
        i = 1:n_feed
      ) <= 0
    ) |>
    add_constraint(
      sum_over(
        x[i] * feed$DM[i] * (feed$Ca[i] - requirement$Ca_min),
        i = 1:n_feed
      ) >= 0
    ) |>
    add_constraint(
      sum_over(
        x[i] * feed$DM[i] * (feed$Ca[i] - requirement$Ca_max),
        i = 1:n_feed
      ) <= 0
    ) |>
    add_constraint(
      sum_over(
        x[i] * feed$DM[i] * (feed$P[i] - requirement$P_min),
        i = 1:n_feed
      ) >= 0
    ) |>
    add_constraint(
      sum_over(
        x[i] * feed$DM[i] * (feed$P[i] - requirement$P_max),
        i = 1:n_feed
      ) <= 0
    ) |>
    add_constraint(
      sum_over(
        x[i] * feed$DM[i] * (feed$forage[i] - requirement$forage_min),
        i = 1:n_feed
      ) >= 0
    ) |>
    add_constraint(
      sum_over(
        x[i] * feed$DM[i] * (feed$forage[i] - requirement$forage_max),
        i = 1:n_feed
      ) <= 0
    )
}

objective_coefficients <- function(feed) {
  list(
    GHG = feed$GHG,
    NFP = feed$NFP,
    Cost = feed$price / 1000
  )
}

safe_solve <- function(model) {
  tryCatch(
    {
      result <- solve_model(model, with_ROI(solver = "glpk"))
      status <- as.character(solver_status(result))
      list(
        ok = identical(tolower(status), "success"),
        result = result,
        status = status,
        detail = if (identical(tolower(status), "success")) {
          "GLPK reported a feasible optimum."
        } else {
          paste("GLPK/ROI status:", status)
        },
        error = ""
      )
    },
    error = function(error) {
      list(
        ok = FALSE,
        result = NULL,
        status = "R_ERROR",
        detail = "R stopped before a solver result was available.",
        error = conditionMessage(error)
      )
    }
  )
}

extract_x <- function(result, n_feed) {
  solution <- get_solution(result, x[i])
  if (!is.data.frame(solution) || nrow(solution) == 0) {
    stop("The solver did not return indexed feed variables.", call. = FALSE)
  }
  values <- rep(NA_real_, n_feed)
  indices <- as.integer(solution$i)
  if (any(indices < 1 | indices > n_feed)) {
    stop("The solver returned an unexpected feed index.", call. = FALSE)
  }
  values[indices] <- as.numeric(solution$value)
  if (anyNA(values) || any(!is.finite(values))) {
    stop("The solver returned an incomplete feed solution.", call. = FALSE)
  }
  if (any(values < -FEASIBILITY_TOL)) {
    stop("The solver returned a materially negative feed amount.", call. = FALSE)
  }
  values[abs(values) <= FEASIBILITY_TOL] <- 0
  values
}

calculate_metrics <- function(x_value, feed) {
  dmi <- sum(x_value * feed$DM)
  if (!is.finite(dmi) || dmi <= 0) {
    return(setNames(rep(NA_real_, 11), c(
      "DMI", "NEL", "CP", "NDF", "Ca", "P", "forage",
      "GHG", "NFP", "Cost", "fresh_weight"
    )))
  }
  c(
    DMI = dmi,
    NEL = sum(x_value * feed$DM * feed$NEL) / dmi,
    CP = sum(x_value * feed$DM * feed$CP) / dmi,
    NDF = sum(x_value * feed$DM * feed$NDF) / dmi,
    Ca = sum(x_value * feed$DM * feed$Ca) / dmi,
    P = sum(x_value * feed$DM * feed$P) / dmi,
    forage = sum(x_value * feed$DM * feed$forage) / dmi,
    GHG = sum(x_value * feed$GHG),
    NFP = sum(x_value * feed$NFP),
    Cost = sum(x_value * feed$price / 1000),
    fresh_weight = sum(x_value)
  )
}

single_objective_run <- function(feed, requirement, objective_name) {
  coefficients <- objective_coefficients(feed)
  n_feed <- nrow(feed)
  model <- build_base_model(feed, requirement)

  if (objective_name == "GHG") {
    model <- model |>
      set_objective(
        sum_over(x[i] * coefficients$GHG[i], i = 1:n_feed),
        sense = "min"
      )
  } else if (objective_name == "NFP") {
    model <- model |>
      set_objective(
        sum_over(x[i] * coefficients$NFP[i], i = 1:n_feed),
        sense = "min"
      )
  } else if (objective_name == "Cost") {
    model <- model |>
      set_objective(
        sum_over(x[i] * coefficients$Cost[i], i = 1:n_feed),
        sense = "min"
      )
  } else {
    stop("Unknown objective: ", objective_name, call. = FALSE)
  }

  solved <- safe_solve(model)
  if (!solved$ok) {
    return(c(solved, list(
      x = NULL,
      metrics = NULL,
      objective = objective_name
    )))
  }

  x_value <- extract_x(solved$result, n_feed)
  c(solved, list(
    x = x_value,
    metrics = calculate_metrics(x_value, feed),
    objective = objective_name
  ))
}

build_payoff <- function(feed, requirement) {
  runs <- lapply(
    OBJECTIVE_NAMES,
    function(objective) single_objective_run(feed, requirement, objective)
  )
  names(runs) <- OBJECTIVE_NAMES

  if (!all(vapply(runs, function(run) run$ok, logical(1)))) {
    return(list(
      ok = FALSE,
      runs = runs,
      payoff = NULL,
      ideal = NULL,
      anti = NULL,
      range = NULL,
      active = NULL
    ))
  }

  payoff <- data.frame(
    solution = paste0(OBJECTIVE_NAMES, "_min"),
    GHG = vapply(runs, function(run) unname(run$metrics["GHG"]), numeric(1)),
    NFP = vapply(runs, function(run) unname(run$metrics["NFP"]), numeric(1)),
    Cost = vapply(runs, function(run) unname(run$metrics["Cost"]), numeric(1)),
    stringsAsFactors = FALSE
  )
  ideal <- vapply(OBJECTIVE_NAMES, function(name) min(payoff[[name]]), numeric(1))
  anti <- vapply(OBJECTIVE_NAMES, function(name) max(payoff[[name]]), numeric(1))
  ranges <- anti - ideal

  list(
    ok = TRUE,
    runs = runs,
    payoff = payoff,
    ideal = ideal,
    anti = anti,
    range = ranges,
    active = ranges > TOL
  )
}

normalized_deviations <- function(metrics, ideal, ranges, active) {
  deviations <- setNames(rep(0, length(OBJECTIVE_NAMES)), OBJECTIVE_NAMES)
  for (objective in OBJECTIVE_NAMES) {
    if (isTRUE(active[[objective]])) {
      value <- (metrics[[objective]] - ideal[[objective]]) / ranges[[objective]]
      deviations[[objective]] <- if (abs(value) <= TOL) 0 else value
    }
  }
  deviations
}

# S2 minimizes the equally weighted normalized deviations from the payoff ideal.
# Constant ideal terms are omitted from the linear objective and restored in the
# reported normalized score; they do not affect the optimizer.
solve_s2_equal_weight <- function(feed, requirement, payoff_info) {
  if (!payoff_info$ok) {
    return(list(
      ok = FALSE,
      result = NULL,
      status = "SKIPPED_PAYOFF_INCOMPLETE",
      detail = "At least one single-objective model did not solve.",
      error = "",
      x = NULL,
      metrics = NULL,
      deviations = NULL,
      combined_objective = NA_real_
    ))
  }

  active_names <- OBJECTIVE_NAMES[payoff_info$active]
  if (length(active_names) == 0) {
    reused <- payoff_info$runs$GHG
    deviations <- normalized_deviations(
      reused$metrics,
      payoff_info$ideal,
      payoff_info$range,
      payoff_info$active
    )
    return(list(
      ok = TRUE,
      result = reused$result,
      status = "success",
      detail = "All payoff ranges were zero; the GHG minimum was reused.",
      error = "",
      x = reused$x,
      metrics = reused$metrics,
      deviations = deviations,
      combined_objective = 0
    ))
  }

  coefficients <- objective_coefficients(feed)
  n_feed <- nrow(feed)
  combined_coefficient <- rep(0, n_feed)
  for (objective in active_names) {
    combined_coefficient <- combined_coefficient +
      OBJECTIVE_WEIGHTS[[objective]] *
      coefficients[[objective]] / payoff_info$range[[objective]]
  }

  model <- build_base_model(feed, requirement) |>
    set_objective(
      sum_over(x[i] * combined_coefficient[i], i = 1:n_feed),
      sense = "min"
    )
  solved <- safe_solve(model)
  if (!solved$ok) {
    return(c(solved, list(
      x = NULL,
      metrics = NULL,
      deviations = NULL,
      combined_objective = NA_real_
    )))
  }

  x_value <- extract_x(solved$result, n_feed)
  metrics <- calculate_metrics(x_value, feed)
  deviations <- normalized_deviations(
    metrics,
    payoff_info$ideal,
    payoff_info$range,
    payoff_info$active
  )
  combined <- sum(
    OBJECTIVE_WEIGHTS[active_names] * deviations[active_names]
  )
  if (abs(combined) <= TOL) combined <- 0

  c(solved, list(
    x = x_value,
    metrics = metrics,
    deviations = deviations,
    combined_objective = combined
  ))
}

validate_feasible_metrics <- function(metrics, requirement, label) {
  values <- c(
    DMI = metrics[["DMI"]],
    NEL = metrics[["NEL"]],
    CP = metrics[["CP"]],
    NDF = metrics[["NDF"]],
    Ca = metrics[["Ca"]],
    P = metrics[["P"]],
    forage = metrics[["forage"]]
  )
  lower <- c(
    DMI = requirement$DMI_min,
    NEL = requirement$NEL_min,
    CP = requirement$CP_min,
    NDF = requirement$NDF_min,
    Ca = requirement$Ca_min,
    P = requirement$P_min,
    forage = requirement$forage_min
  )
  upper <- c(
    DMI = requirement$DMI_max,
    NEL = requirement$NEL_max,
    CP = requirement$CP_max,
    NDF = requirement$NDF_max,
    Ca = requirement$Ca_max,
    P = requirement$P_max,
    forage = requirement$forage_max
  )
  failed <- names(values)[
    !is.finite(values) |
      values < lower - FEASIBILITY_TOL |
      values > upper + FEASIBILITY_TOL
  ]
  if (length(failed) > 0) {
    stop(
      label,
      " failed the post-solve feasibility check for: ",
      paste(failed, collapse = ", "),
      call. = FALSE
    )
  }
  invisible(TRUE)
}

make_status_row <- function(group_id, stage_id, model_name, run) {
  data.frame(
    synthetic = run_is_synthetic,
    group_id = group_id,
    stage_id = stage_id,
    model = model_name,
    solver_status = run$status,
    solver_detail = run$detail,
    r_error = run$error,
    warning = run_warning,
    stringsAsFactors = FALSE
  )
}

make_summary_row <- function(
    group_id,
    stage_id,
    scenario,
    run,
    deviations = NULL,
    combined_score = NA_real_) {
  metrics <- run$metrics
  if (is.null(metrics)) {
    metrics <- setNames(rep(NA_real_, 11), c(
      "DMI", "NEL", "CP", "NDF", "Ca", "P", "forage",
      "GHG", "NFP", "Cost", "fresh_weight"
    ))
  }
  if (is.null(deviations)) {
    deviations <- c(GHG = NA_real_, NFP = NA_real_, Cost = NA_real_)
  }
  data.frame(
    synthetic = run_is_synthetic,
    group_id = group_id,
    stage_id = stage_id,
    scenario = scenario,
    solver_status = run$status,
    dmi_kg_day = unname(metrics[["DMI"]]),
    nel_mj_per_kg_dm = unname(metrics[["NEL"]]),
    crude_protein_pct_dm = 100 * unname(metrics[["CP"]]),
    ndf_pct_dm = 100 * unname(metrics[["NDF"]]),
    calcium_pct_dm = 100 * unname(metrics[["Ca"]]),
    phosphorus_pct_dm = 100 * unname(metrics[["P"]]),
    forage_pct_dm = 100 * unname(metrics[["forage"]]),
    ghg_kg_co2e_day = unname(metrics[["GHG"]]),
    nfp_g_n_day = unname(metrics[["NFP"]]),
    cost_unit_day = unname(metrics[["Cost"]]),
    fresh_feed_kg_day = unname(metrics[["fresh_weight"]]),
    normalized_deviation_ghg = unname(deviations[["GHG"]]),
    normalized_deviation_nfp = unname(deviations[["NFP"]]),
    normalized_deviation_cost = unname(deviations[["Cost"]]),
    equal_weight_ghg = unname(OBJECTIVE_WEIGHTS[["GHG"]]),
    equal_weight_nfp = unname(OBJECTIVE_WEIGHTS[["NFP"]]),
    equal_weight_cost = unname(OBJECTIVE_WEIGHTS[["Cost"]]),
    combined_normalized_score = combined_score,
    warning = run_warning,
    stringsAsFactors = FALSE
  )
}

make_diet_rows <- function(group_id, stage_id, scenario, run, feed) {
  if (!run$ok || is.null(run$x)) return(NULL)
  data.frame(
    synthetic = run_is_synthetic,
    group_id = group_id,
    stage_id = stage_id,
    scenario = scenario,
    feed_id = feed$feed_id,
    feed_label = feed$feed_label,
    fresh_feed_kg_day = as.numeric(run$x),
    dry_matter_kg_day = as.numeric(run$x * feed$DM),
    solver_status = run$status,
    warning = run_warning,
    stringsAsFactors = FALSE
  )
}

make_payoff_rows <- function(group_id, stage_id, payoff_info) {
  if (!payoff_info$ok) return(NULL)
  payoff <- payoff_info$payoff
  data.frame(
    synthetic = run_is_synthetic,
    group_id = group_id,
    stage_id = stage_id,
    solution = payoff$solution,
    ghg_kg_co2e_day = payoff$GHG,
    nfp_g_n_day = payoff$NFP,
    cost_unit_day = payoff$Cost,
    ideal_ghg = unname(payoff_info$ideal[["GHG"]]),
    anti_ghg = unname(payoff_info$anti[["GHG"]]),
    range_ghg = unname(payoff_info$range[["GHG"]]),
    ideal_nfp = unname(payoff_info$ideal[["NFP"]]),
    anti_nfp = unname(payoff_info$anti[["NFP"]]),
    range_nfp = unname(payoff_info$range[["NFP"]]),
    ideal_cost = unname(payoff_info$ideal[["Cost"]]),
    anti_cost = unname(payoff_info$anti[["Cost"]]),
    range_cost = unname(payoff_info$range[["Cost"]]),
    active_ghg = unname(payoff_info$active[["GHG"]]),
    active_nfp = unname(payoff_info$active[["NFP"]]),
    active_cost = unname(payoff_info$active[["Cost"]]),
    warning = run_warning,
    stringsAsFactors = FALSE
  )
}

diet_rows <- list()
payoff_rows <- list()
summary_rows <- list()
status_rows <- list()
all_required_scenarios_success <- TRUE

for (row_index in seq_len(nrow(constraints))) {
  requirement <- constraints[row_index, , drop = FALSE]
  group_id <- requirement$group_id[[1]]
  stage_id <- requirement$stage_id[[1]]

  payoff_info <- build_payoff(feed, requirement)
  for (objective in OBJECTIVE_NAMES) {
    status_rows[[length(status_rows) + 1]] <- make_status_row(
      group_id,
      stage_id,
      paste0(objective, "_min"),
      payoff_info$runs[[objective]]
    )
  }

  if (payoff_info$ok) {
    payoff_rows[[length(payoff_rows) + 1]] <- make_payoff_rows(
      group_id,
      stage_id,
      payoff_info
    )
    for (objective in OBJECTIVE_NAMES) {
      run <- payoff_info$runs[[objective]]
      deviations <- normalized_deviations(
        run$metrics,
        payoff_info$ideal,
        payoff_info$range,
        payoff_info$active
      )
      score <- sum(
        OBJECTIVE_WEIGHTS[payoff_info$active] *
          deviations[payoff_info$active]
      )
      summary_rows[[length(summary_rows) + 1]] <- make_summary_row(
        group_id,
        stage_id,
        paste0(objective, "_min"),
        run,
        deviations,
        score
      )
    }
  } else {
    for (objective in OBJECTIVE_NAMES) {
      summary_rows[[length(summary_rows) + 1]] <- make_summary_row(
        group_id,
        stage_id,
        paste0(objective, "_min"),
        payoff_info$runs[[objective]]
      )
    }
  }

  s1 <- payoff_info$runs$GHG
  if (s1$ok) {
    validate_feasible_metrics(
      s1$metrics,
      requirement,
      paste(group_id, stage_id, "S1_GHG_min", sep = " / ")
    )
    diet_rows[[length(diet_rows) + 1]] <- make_diet_rows(
      group_id,
      stage_id,
      "S1_GHG_min",
      s1,
      feed
    )
  } else {
    all_required_scenarios_success <- FALSE
  }

  s2 <- solve_s2_equal_weight(feed, requirement, payoff_info)
  status_rows[[length(status_rows) + 1]] <- make_status_row(
    group_id,
    stage_id,
    "S2_equal_weight_weighted_sum",
    s2
  )
  summary_rows[[length(summary_rows) + 1]] <- make_summary_row(
    group_id,
    stage_id,
    "S2_equal_weight_weighted_sum",
    s2,
    s2$deviations,
    s2$combined_objective
  )

  if (s2$ok) {
    validate_feasible_metrics(
      s2$metrics,
      requirement,
      paste(group_id, stage_id, sep = " / ")
    )
    diet_rows[[length(diet_rows) + 1]] <- make_diet_rows(
      group_id,
      stage_id,
      "S2_equal_weight_weighted_sum",
      s2,
      feed
    )
  } else {
    all_required_scenarios_success <- FALSE
  }
}

bind_rows_or_empty <- function(rows, empty_frame) {
  kept <- Filter(Negate(is.null), rows)
  if (length(kept) == 0) return(empty_frame)
  do.call(rbind, kept)
}

diet_output <- bind_rows_or_empty(
  diet_rows,
  data.frame(
    synthetic = logical(),
    group_id = character(),
    stage_id = character(),
    scenario = character(),
    feed_id = character(),
    feed_label = character(),
    fresh_feed_kg_day = numeric(),
    dry_matter_kg_day = numeric(),
    solver_status = character(),
    warning = character(),
    stringsAsFactors = FALSE
  )
)
payoff_output <- bind_rows_or_empty(payoff_rows, data.frame())
summary_output <- bind_rows_or_empty(summary_rows, data.frame())
status_output <- bind_rows_or_empty(status_rows, data.frame())

dir.create(cli$output_dir, recursive = TRUE, showWarnings = FALSE)
if (!dir.exists(cli$output_dir)) {
  stop("Could not create output directory: ", cli$output_dir, call. = FALSE)
}

options(digits = 15, scipen = 999)
write_public_csv <- function(data, filename) {
  write.csv(
    data,
    file.path(cli$output_dir, filename),
    row.names = FALSE,
    na = "",
    fileEncoding = "UTF-8"
  )
}

write_public_csv(diet_output, "optimized_diet.csv")
write_public_csv(payoff_output, "optimization_payoff_matrix.csv")
write_public_csv(summary_output, "optimization_summary.csv")
write_public_csv(status_output, "optimization_solver_status.csv")

if (!all_required_scenarios_success) {
  stop(
    "At least one group/stage did not produce feasible S1 and S2 solutions. ",
    "Review optimization_solver_status.csv.",
    call. = FALSE
  )
}

if (isTRUE(cli$example)) {
  cat("synthetic optimization run passed\n")
}
cat("solver: glpk\n")
cat("weights: GHG=1/3, NFP=1/3, Cost=1/3\n")
cat(
  "outputs: ",
  cli$output_dir,
  "\n",
  sep = ""
)
