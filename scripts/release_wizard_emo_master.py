from release_wizard_common import main


if __name__ == '__main__':
  raise SystemExit(
    main(
      fixedTarget='emo-master',
      localStateName='.release-wizard-emo-master.local.json',
    )
  )
