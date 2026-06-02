from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from app.core.database import get_db
from app.models.supplier_profile import SupplierProfile
router = APIRouter(tags=["suppliers"])


class SupplierProfileCreate(BaseModel):
    supplier_code: str
    name: str
    siret: Optional[str] = None
    vat_number: Optional[str] = None
    name_aliases: list[str] = []
    field_aliases: dict = {}
    number_locale: str = "fr"
    date_format: str = "%d/%m/%Y"
    price_tolerance: Optional[float] = None
    quantity_tolerance: Optional[float] = None
    ref_patterns: list[str] = []
    column_layout: dict = {}
    known_products: list[dict] = []
    ocr_corrections: dict = {}
    doc_type_keywords: list[str] = []
    is_confirmed: bool = True


@router.post("/suppliers", status_code=status.HTTP_201_CREATED)
async def create_supplier_profile(
    profile: SupplierProfileCreate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SupplierProfile).where(SupplierProfile.supplier_code == profile.supplier_code)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Supplier '{profile.supplier_code}' already exists"
        )
    
    new_profile = SupplierProfile(
        supplier_code=profile.supplier_code,
        name=profile.name,
        siret=profile.siret,
        vat_number=profile.vat_number,
        name_aliases=profile.name_aliases,
        field_aliases=profile.field_aliases,
        number_locale=profile.number_locale,
        date_format=profile.date_format,
        price_tolerance=profile.price_tolerance,
        quantity_tolerance=profile.quantity_tolerance,
        ref_patterns=profile.ref_patterns,
        column_layout=profile.column_layout,
        known_products=profile.known_products,
        ocr_corrections=profile.ocr_corrections,
        doc_type_keywords=profile.doc_type_keywords,
        is_confirmed=profile.is_confirmed,
        confidence_score=1.0 if profile.is_confirmed else 0.5,
        auto_detected=False,
    )
    
    db.add(new_profile)
    await db.commit()
    await db.refresh(new_profile)
    
    return {
        "id": new_profile.id,
        "supplier_code": new_profile.supplier_code,
        "name": new_profile.name,
        "message": "Supplier profile created successfully"
    }


@router.get("/suppliers")
async def list_supplier_profiles(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SupplierProfile).order_by(SupplierProfile.name))
    profiles = result.scalars().all()
    
    return {
        "total": len(profiles),
        "suppliers": [
            {
                "id": p.id,
                "supplier_code": p.supplier_code,
                "name": p.name,
                "is_confirmed": p.is_confirmed,
            }
            for p in profiles
        ]
    }
