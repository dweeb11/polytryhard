from sqlalchemy import BigInteger, Column, Enum


def Cents(nullable: bool = False) -> Column[int]:
    return Column(BigInteger, nullable=nullable)


def str_enum_column(enum_type: type) -> Enum:
    return Enum(
        enum_type,
        native_enum=False,
        values_callable=lambda obj: [member.value for member in obj],
    )
