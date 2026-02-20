# Changelog

All notable changes to this project will be documented in this file.

## [0.1.1] - 2026-02-20

### Fixed
- `_calculate_material_requirements()` referenced `inp.input_product` instead of `inp.item` (GenericForeignKey), causing `AttributeError` when calling `craft.start()`.

## [0.1.0] - 2025-01-20

### Added
- Recipe model with ingredients (Bill of Materials)
- IngredientCategory for ingredient organization
- Plan and PlanItem models for production planning
- WorkOrder model with step-based execution
- Craft service facade (plan, approve, schedule)
- Coefficient method for ingredient calculation
- Admin interface with optional Unfold support
- Daily ingredients view with template
- Stockman and Offerman integration adapters
- Django management command for demo data
