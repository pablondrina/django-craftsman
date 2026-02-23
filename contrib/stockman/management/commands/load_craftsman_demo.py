"""
Load demo data for Craftsman v2.3.

Creates realistic production data for a bakery:
- Recipes for all batch-produced products
- Plans and PlanItems (2 weeks past + 1 week future)
- WorkOrders with step tracking
- Holds (demandas) for testing "Sugerido"

Usage:
    python manage.py load_craftsman_demo
    python manage.py load_craftsman_demo --clear
"""

import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.utils import timezone

User = get_user_model()


class Command(BaseCommand):
    help = "Carrega dados de demonstração para o Craftsman v2.3"

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Limpa dados existentes antes de carregar",
        )

    def handle(self, *args, **options):
        from offerman.models import Product
        from stockman.models import Hold, HoldStatus, Position

        from craftsman.models import (
            Plan,
            PlanItem,
            PlanStatus,
            Recipe,
            RecipeItem,
            WorkOrder,
            WorkOrderStatus,
        )

        self.stdout.write("=" * 60)
        self.stdout.write("🍞 Carregando dados de demonstração do Craftsman v2.3...")
        self.stdout.write("=" * 60)

        # Clear if requested
        if options["clear"]:
            self.stdout.write("\n🗑️  Limpando dados existentes...")
            Hold.objects.all().delete()
            WorkOrder.objects.all().delete()
            PlanItem.objects.all().delete()
            Plan.objects.all().delete()
            RecipeItem.objects.all().delete()
            Recipe.objects.all().delete()
            self.stdout.write(self.style.SUCCESS("   ✓ Dados limpos"))

        # Get or create users
        users = self._create_users()

        # Get destination position
        destination = Position.objects.filter(is_default=True).first()
        if not destination:
            self.stdout.write(
                self.style.ERROR(
                    "❌ Nenhuma Position padrão encontrada. Rode o setup do Stockman primeiro."
                )
            )
            return

        # Get batch-produced products
        products = Product.objects.filter(is_batch_produced=True, is_active=True)
        if not products.exists():
            self.stdout.write(
                self.style.ERROR(
                    "❌ Nenhum produto com is_batch_produced=True encontrado."
                )
            )
            return

        self.stdout.write(
            f"\n📦 Encontrados {products.count()} produtos para criar receitas"
        )

        # Create recipes
        recipes = self._create_recipes(products, destination)

        # Create holds (demands) for future dates
        self._create_holds(products)

        # Create plans and work orders
        # Past: 14 days, Future: 7 days
        self._create_plans_and_work_orders(recipes, destination, users)

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(
            self.style.SUCCESS("✅ Dados de demonstração carregados com sucesso!")
        )
        self.stdout.write("=" * 60)
        self._print_summary()

    def _print_summary(self):
        """Print summary of created data."""
        from craftsman.models import Plan, PlanItem, Recipe, WorkOrder
        from stockman.models import Hold

        self.stdout.write("\n📊 Resumo:")
        self.stdout.write(f"   • {Recipe.objects.count()} receitas")
        self.stdout.write(f"   • {Plan.objects.count()} planos")
        self.stdout.write(f"   • {PlanItem.objects.count()} itens de plano")
        self.stdout.write(f"   • {WorkOrder.objects.count()} ordens de produção")
        self.stdout.write(f"   • {Hold.objects.count()} holds (encomendas)")

        today = date.today()
        past_start = today - timedelta(days=14)
        future_end = today + timedelta(days=7)
        self.stdout.write(
            f"   • Período: {past_start.strftime('%d/%m')} a {future_end.strftime('%d/%m')}"
        )

        # Step field stats
        with_process = WorkOrder.objects.filter(process_quantity__isnull=False).count()
        with_output = WorkOrder.objects.filter(
            output_quantity__isnull=False
        ).count()
        self.stdout.write(f"\n📈 Campos preenchidos:")
        self.stdout.write(f"   • process_quantity: {with_process}")
        self.stdout.write(f"   • output_quantity: {with_output}")

        # Holds stats
        future_holds = Hold.objects.filter(target_date__gt=today).count()
        self.stdout.write(f"\n📋 Holds futuros (encomendas): {future_holds}")

    def _create_users(self):
        """Create demo users for production team."""
        users = {}
        user_data = [
            ("joao", "João", "Silva", "Padeiro Senior"),
            ("maria", "Maria", "Santos", "Confeiteira"),
            ("pedro", "Pedro", "Oliveira", "Auxiliar"),
        ]

        for username, first_name, last_name, role in user_data:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": f"{username}@padaria.local",
                    "is_staff": True,
                },
            )
            if created:
                user.set_password("demo123")
                user.save()
                self.stdout.write(f"   ✓ Usuário criado: {first_name} ({role})")
            users[username] = user

        return users

    def _create_recipes(self, products, work_center):
        """Create recipes for all products."""
        from craftsman.models import Recipe

        self.stdout.write("\n🍰 Criando receitas...")

        ct = ContentType.objects.get_for_model(products.first())
        recipes = {}

        for product in products:
            existing = Recipe.objects.filter(
                output_type=ct,
                output_id=product.pk,
                is_active=True,
            ).first()

            if existing:
                if existing.steps != ["Mixing", "Shaping", "Baking"]:
                    existing.steps = ["Mixing", "Shaping", "Baking"]
                    existing.save()
                recipes[product.pk] = existing
                continue

            # Determine base quantity
            if "croissant" in product.name.lower():
                output_qty = 30
            elif "brioche" in product.name.lower():
                output_qty = 20
            elif "baguette" in product.name.lower():
                output_qty = 40
            else:
                output_qty = 20

            recipe = Recipe.objects.create(
                code=f"{product.slug}-v1",
                name=f"Receita {product.name}",
                output_type=ct,
                output_id=product.pk,
                output_quantity=Decimal(str(output_qty)),
                duration_minutes=90,
                lead_time_days=0,
                steps=["Mixing", "Shaping", "Baking"],
                work_center=work_center,
                is_active=True,
            )
            recipes[product.pk] = recipe
            self.stdout.write(f"   ✓ {recipe.name}")

        return recipes

    def _create_holds(self, products):
        """Create holds (demands) for future dates to test 'Sugerido'."""
        from stockman.models import Hold, HoldStatus

        self.stdout.write("\n📋 Criando encomendas (holds)...")

        today = date.today()
        ct = ContentType.objects.get_for_model(products.first())

        # Create holds for next 7 days
        holds_created = 0
        for days_ahead in range(1, 8):
            target_date = today + timedelta(days=days_ahead)

            # Random subset of products
            products_for_day = random.sample(list(products), min(4, products.count()))

            for product in products_for_day:
                # Random quantity (simulating customer orders)
                qty = random.randint(5, 30)

                Hold.objects.create(
                    content_type=ct,
                    object_id=product.pk,
                    quant=None,  # Demand (no stock yet)
                    quantity=Decimal(str(qty)),
                    target_date=target_date,
                    status=HoldStatus.PENDING,
                    metadata={
                        "source": "demo",
                        "customer": f"Cliente {random.randint(1, 100)}",
                    },
                )
                holds_created += 1

        self.stdout.write(f"   ✓ {holds_created} encomendas criadas (próximos 7 dias)")

    def _create_plans_and_work_orders(self, recipes, destination, users):
        """Create plans and work orders for past and future."""
        from craftsman.models import (
            Plan,
            PlanItem,
            PlanStatus,
            WorkOrder,
            WorkOrderStatus,
        )

        self.stdout.write("\n📋 Criando planos e ordens de produção...")

        today = date.today()
        user_list = list(users.values())

        # Past 14 days + Today + Future 7 days = 22 days
        for days_offset in range(-14, 8):
            target_date = today + timedelta(days=days_offset)
            is_today = days_offset == 0
            is_future = days_offset > 0
            is_past = days_offset < 0

            weekdays = ["SEG", "TER", "QUA", "QUI", "SEX", "SAB", "DOM"]
            weekday = weekdays[target_date.weekday()]

            # Skip weekends for future (optional production)
            if is_future and target_date.weekday() >= 5:
                continue

            self.stdout.write(
                f"\n   📅 {weekday} {target_date.strftime('%d/%m/%Y')} "
                f"{'(HOJE)' if is_today else '(FUTURO)' if is_future else ''}"
            )

            # Create Plan
            plan, _ = Plan.objects.get_or_create(
                date=target_date,
                defaults={"status": PlanStatus.DRAFT},
            )

            # Create PlanItems for all recipes
            for recipe in recipes.values():
                base_qty = int(recipe.output_quantity) * random.randint(1, 3)

                plan_item, created = PlanItem.objects.get_or_create(
                    plan=plan,
                    recipe=recipe,
                    defaults={
                        "quantity": Decimal(str(base_qty)),
                        "destination": destination,
                    },
                )

                if not created:
                    continue

                # Only create WorkOrders for past and today
                if is_past or is_today:
                    work = self._create_work_order(
                        plan_item, destination, users, target_date
                    )

                    if is_past:
                        # Past: all completed
                        self._simulate_complete(work, recipe, users)
                        plan.status = PlanStatus.COMPLETED
                        plan.scheduled_at = timezone.now() - timedelta(
                            days=-days_offset
                        )
                        plan.completed_at = timezone.now() - timedelta(
                            days=-days_offset - 1
                        )
                        plan.save()
                    elif is_today:
                        # Today: variety of states
                        self._simulate_today_workflow(work, recipe, users)
                        plan.status = PlanStatus.SCHEDULED
                        plan.scheduled_at = timezone.now()
                        plan.save()
                else:
                    # Future: just plans, no WorkOrders yet
                    pass

            # Count statuses
            pending = WorkOrder.objects.filter(
                plan_item__plan=plan,
                status=WorkOrderStatus.PENDING,
            ).count()
            in_progress = WorkOrder.objects.filter(
                plan_item__plan=plan,
                status=WorkOrderStatus.IN_PROGRESS,
            ).count()
            completed = WorkOrder.objects.filter(
                plan_item__plan=plan,
                status=WorkOrderStatus.COMPLETED,
            ).count()

            items_count = plan.items.count()
            if is_future:
                self.stdout.write(
                    f"      → {items_count} itens planejados (sem WorkOrders ainda)"
                )
            else:
                self.stdout.write(
                    f"      → {items_count} itens: {pending} pend, {in_progress} prog, {completed} conc"
                )

    def _create_work_order(self, plan_item, destination, users, target_date):
        """Create a WorkOrder for a PlanItem."""
        from craftsman.models import WorkOrder, WorkOrderStatus

        user_list = list(users.values())

        scheduled_start = datetime.combine(target_date, time(5, 0))
        scheduled_start = timezone.make_aware(scheduled_start)

        work = WorkOrder.objects.create(
            plan_item=plan_item,
            recipe=plan_item.recipe,
            planned_quantity=plan_item.quantity,
            status=WorkOrderStatus.PENDING,
            destination=destination,
            assigned_to=random.choice(user_list),
            scheduled_start=scheduled_start,
            metadata={"step_log": []},
        )
        return work

    def _simulate_today_workflow(self, work, recipe, users):
        """Simulate today's workflow with variety of states."""
        from craftsman.models import WorkOrder, WorkOrderStatus

        user_list = list(users.values())
        choice = random.random()

        if choice < 0.15:
            # 15% - Pending
            pass
        elif choice < 0.30:
            # 15% - Just started mixing
            qty = float(work.planned_quantity) * random.uniform(0.95, 1.02)
            work.step("Mixing", Decimal(str(round(qty))), user=random.choice(user_list))
        elif choice < 0.50:
            # 20% - Mixing + Shaping done
            mix_qty = float(work.planned_quantity) * random.uniform(0.95, 1.02)
            shape_qty = mix_qty * random.uniform(0.96, 1.0)
            work.step(
                "Mixing", Decimal(str(round(mix_qty))), user=random.choice(user_list)
            )
            work = WorkOrder.objects.get(pk=work.pk)
            work.step(
                "Shaping", Decimal(str(round(shape_qty))), user=random.choice(user_list)
            )
        else:
            # 50% - Completed
            self._simulate_complete(work, recipe, users)

    def _simulate_complete(self, work, recipe, users):
        """Simulate completing a work order with all steps."""
        from craftsman.models import WorkOrder, WorkOrderStatus

        user_list = list(users.values())
        work = WorkOrder.objects.get(pk=work.pk)

        if work.status == WorkOrderStatus.COMPLETED:
            return

        base_qty = float(work.planned_quantity)
        mixing_qty = round(base_qty * random.uniform(0.98, 1.05))
        processed_qty = round(mixing_qty * random.uniform(0.95, 0.99))
        produced_qty = round(processed_qty * random.uniform(0.94, 0.99))

        work.step("Mixing", Decimal(str(mixing_qty)), user=random.choice(user_list))
        work = WorkOrder.objects.get(pk=work.pk)

        work.step("Shaping", Decimal(str(processed_qty)), user=random.choice(user_list))
        work = WorkOrder.objects.get(pk=work.pk)

        work.step("Baking", Decimal(str(produced_qty)), user=random.choice(user_list))
        work = WorkOrder.objects.get(pk=work.pk)

        if work.status != WorkOrderStatus.COMPLETED:
            work.complete(
                Decimal(str(produced_qty)),
                user=random.choice(user_list),
            )
